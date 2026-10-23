"""Export aggregate interactive charts from the existing bus analysis."""

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

import charts
import analyse_routes
from build_trajectories import longest_collection_run

ROOT = Path(__file__).resolve().parents[1]


def load_summary(name: str) -> dict:
    return json.loads((ROOT / "docs" / f"{name}_summary.json").read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=Path, default=ROOT / "data" / "processed" / "trajectories.parquet")
    args = parser.parse_args()
    steps = pd.read_parquet(args.steps, columns=["time", "step", "lat", "lon", "dist_m", "dt_s", "speed_kmh"])
    steps = steps[steps.step == "ok"]
    summary = load_summary("realtime")
    if len(steps) != summary["steps"]:
        raise ValueError("Usable step count differs from realtime_summary.json.")
    slot = steps.time.dt.floor("15min")
    complete = slot < steps.time.max().floor("15min")
    quantiles = steps[complete].groupby(slot[complete]).speed_kmh.quantile([0.25, 0.5, 0.75]).unstack()
    time = quantiles.index.strftime("%H:%M").tolist()
    q = {p: quantiles[p].round(2).tolist() for p in [0.25, 0.5, 0.75]}
    timeline = {
        "label": "Speed through the evening", "yTitle": "Bus speed (km/h)",
        "note": "Median and middle 50% of usable GPS-step speeds in 15-minute bins. Parked buses are excluded. The first bin is partial; the last partial bin is omitted. Times are IST.",
        "traces": [
            {"type": "scatter", "name": "25th percentile", "x": time, "y": q[0.25], "mode": "lines", "line": {"width": 0}, "showlegend": False},
            {"type": "scatter", "name": "Middle 50%", "x": time, "y": q[0.75], "mode": "lines", "line": {"width": 0}, "fill": "tonexty", "fillcolor": "rgba(36,100,84,0.12)"},
            {"type": "scatter", "name": "Median", "x": time, "y": q[0.5], "mode": "lines+markers", "line": {"color": "#246454"}, "marker": {"color": "#246454"}}
        ],
        "columns": ["Time (IST)", "25th percentile", "Median km/h", "75th percentile"],
        "rows": list(zip(time, q[0.25], q[0.5], q[0.75])), "xaxis": {"dtick": 4}
    }
    map_views = {}
    landmarks = charts.landmark_points()
    for key, label, hours in [("peak", "18:23 to 20:00", [18, 19]), ("night", "22:00 to 00:23", [22, 23, 0])]:
        grid, extent = charts.speed_grid(steps[steps.time.dt.hour.isin(hours)], charts.DELHI, 110)
        ny, nx = grid.shape
        x = ((np.arange(nx) + 0.5) * 0.11).round(3).tolist()
        y = ((np.arange(ny) + 0.5) * 0.11).round(3).tolist()
        z = [[round(float(value), 1) if np.isfinite(value) else None for value in row] for row in grid]
        share = charts.share_below(grid, 15)
        rows = [[x[col], y[row], z[row][col]] for row, col in np.argwhere(np.isfinite(grid))]
        annotations = []
        for name in ["Connaught Place", "Anand Vihar", "IGI Airport", "Rohini", "Najafgarh", "Badarpur"]:
            point = landmarks.loc[name]
            px, py = charts.to_mercator(point.lon, point.lat)
            annotations.append({"x": float((px - extent[0]) / 1000), "y": float((py - extent[2]) / 1000), "text": name, "showarrow": False, "font": {"size": 10}, "bgcolor": "rgba(255,254,249,0.85)"})
        map_views[key] = {
            "label": label,
            "note": f"{share:.1%} of qualifying grid cells are below 15 km/h in this window. Each cell is 110 m in Web Mercator; speed is total distance / total time, smoothed over neighbouring cells. At least 3 observations per cell. Blank cells have insufficient coverage, not free roads.",
            "columns": ["Easting from map origin (km)", "Northing from map origin (km)", "Road speed (km/h)"],
            "rows": rows,
            "traces": [{"type": "heatmap", "x": x, "y": y, "z": z, "zmin": 0, "zmax": 40, "hoverongaps": False,
                        "colorscale": [[0, "#a65c38"], [0.375, "#d2a35b"], [0.65, "#8a9a73"], [1, "#246454"]],
                        "colorbar": {"title": {"text": "km/h"}, "thickness": 9, "len": 0.6},
                        "hovertemplate": "Road speed: %{z:.1f} km/h<extra></extra>"}],
            "layout": {"margin": {"l": 0, "r": 35, "t": 0, "b": 0}, "dragmode": "pan", "annotations": annotations,
                       "xaxis": {"visible": False}, "yaxis": {"visible": False, "scaleanchor": "x", "scaleratio": 1}}
        }
    model = load_summary("model")
    methods = ["Historical median", "Own recent speed", "LightGBM"]
    tests = {"same": ("Same hours", model["robustness"]["same_hours"]),
             "unseen": ("Unseen routes", model["robustness"]["unseen_routes"]),
             "later": ("Later evening", model["results"])}
    model_views = {}
    notes = {
        "same": "Alternate 30-minute blocks. This compares methods under similar traffic conditions.",
        "unseen": "A quarter of routes held out. This measures transfer to routes not seen during training.",
        "later": "Train early, test after 21:46. Earlier congestion makes the historical baseline less representative of late-night traffic."
    }
    for key, (label, scores) in tests.items():
        values = [scores[method]["mae_s"] for method in methods]
        model_views[key] = {
            "label": label, "yTitle": "Mean absolute error (seconds)", "note": notes[key],
            "columns": ["Method", "MAE in seconds"], "rows": list(zip(methods, values)),
            "traces": [{"type": "bar", "name": "Error", "x": methods, "y": values,
                        "hovertemplate": "%{x}<br>%{y:.1f} seconds<extra></extra>"}]
        }
    horizon = [str(i) for i in range(1, 11)]
    horizon_values = {method: [model["results"][method]["mae_by_horizon_s"][i] for i in horizon] for method in methods}
    slowest = load_summary("routes")["slowest_segments"]
    segment_views = {}
    labels = [f'{row["from_stop"]} to {row["to_stop"]}' for row in slowest[:5]]
    for key, label, field, unit in [("speed", "Median speed", "median_kmh", "km/h"), ("time", "Median travel time", "median_s", "seconds")]:
        values = [row[field] for row in slowest[:5]]
        segment_views[key] = {
            "label": label, "xTitle": unit,
            "note": "The five slowest qualifying stop-to-stop stretches. Each is at least 250 m long and has at least 10 observed traversals. Straight-line distance can understate road speed.",
            "columns": ["Stretch", unit], "rows": list(zip(labels, values)),
            "traces": [{"type": "bar", "orientation": "h", "x": values, "y": ["Anand Vihar", "Gazipur Depot", "Mahipalpur", "Tilak Nagar", "Moti Nagar"],
                        "text": labels, "hovertemplate": "%{text}<br>%{x:.1f}<extra></extra>"}],
            "yaxis": {"autorange": "reversed"}
        }
    report = {"source": "Delhi OTD GPS, 21 to 22 October 2026; aggregate road grids and saved model results.",
              "charts": {
                  "road-map": {"title": "Road speeds in the observed bus network", "views": map_views},
                  "timeline": {"title": "Bus speeds through the evening", "views": {"all": timeline}},
                  "segments": {"title": "Five slow stop-to-stop stretches", "views": segment_views},
                  "model": {"title": "Arrival prediction across three tests", "views": model_views},
                  "horizon": {"title": "Error by number of stops ahead", "views": {"all": {
                      "label": "Later-evening test", "xTitle": "Stops ahead", "yTitle": "Mean absolute error (seconds)",
                      "note": "Later-evening test only. These curves must not be interpreted as same-hours or unseen-route results.",
                      "columns": ["Stops ahead", *methods],
                      "rows": [[int(h), *[horizon_values[m][i] for m in methods]] for i, h in enumerate(horizon)],
                      "traces": [{"type": "scatter", "mode": "lines+markers", "name": method, "x": horizon, "y": horizon_values[method]} for method in methods]
                  }}}
              }}
    log = pd.read_csv(ROOT / "data" / "raw" / "realtime" / "poll_log.csv")
    start, end = longest_collection_run()
    log = log[log.polled_at.between(start, end)].copy()
    log["time"] = pd.to_datetime(log.polled_at, unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    fleet = log[log.vehicles > 0].set_index("time").vehicles.resample("5min").median().dropna()
    fleet_time = fleet.index.strftime("%H:%M").tolist()
    report["charts"]["fleet"] = {"title": "Buses reporting through the evening", "views": {"all": {
        "label": "Five-minute medians", "yTitle": "Buses in a non-empty response",
        "note": "Five-minute median counts in non-empty feed responses during the six-hour collection. Empty responses are missing coverage, not zero buses. Times are IST.",
        "columns": ["Time (IST)", "Median buses"], "rows": list(zip(fleet_time, fleet.tolist())),
        "traces": [{"type": "scatter", "mode": "lines", "x": fleet_time, "y": fleet.tolist(), "name": "Reported buses"}],
        "xaxis": {"dtick": 12}
    }}}
    joined, _ = analyse_routes.load()
    gaps, by_route = analyse_routes.headways(joined)
    if len(gaps) != load_summary("routes")["headway_gaps"]:
        raise ValueError("Headway counts differ from the saved analysis.")
    gap_counts = pd.cut(gaps.gap_s / 60, [0, 2, 5, 10, 20, 30, np.inf], right=False,
                        labels=["Under 2", "2 to 5", "5 to 10", "10 to 20", "20 to 30", "30 or more"]).value_counts(sort=False)
    report["charts"]["headways"] = {"title": "Gaps between buses", "views": {"all": {
        "label": "Observed gaps", "xTitle": "Gap in minutes", "yTitle": "Share of observed gaps (%)",
        "note": "Consecutive buses on the same route at the same stop. Gaps under two minutes count as bunching. Long gaps can also reflect low scheduled frequency or missing observations.",
        "columns": ["Gap in minutes", "Count", "Share (%)"],
        "rows": [[str(label), int(value), round(value / len(gaps) * 100, 3)] for label, value in gap_counts.items()],
        "traces": [{"type": "bar", "x": gap_counts.index.tolist(), "y": (gap_counts / len(gaps) * 100).round(3).tolist()}]
    }}}
    cv = by_route.replace([np.inf, -np.inf], np.nan).dropna(subset=["cv", "median_gap_s"])
    report["charts"]["reliability"] = {"title": "Service frequency and irregularity", "views": {"all": {
        "label": "Route aggregates", "xTitle": "Median gap between buses (minutes)", "yTitle": "Headway coefficient of variation",
        "note": "Each point is a route aggregate. Route values are medians across stops with at least six distinct buses. A coefficient of variation of one is a reference for random arrivals, not a service target.",
        "columns": ["Route ID", "Median gap (minutes)", "Coefficient of variation"],
        "rows": [[str(route), round(row.median_gap_s / 60, 3), row.cv] for route, row in cv.iterrows()],
        "traces": [{"type": "scatter", "mode": "markers", "name": "Route", "x": (cv.median_gap_s / 60).round(3).tolist(), "y": cv.cv.tolist(),
                    "text": [str(route) for route in cv.index], "marker": {"opacity": 0.55},
                    "hovertemplate": "Route %{text}<br>Median gap: %{x:.1f} min<br>Coefficient: %{y:.2f}<extra></extra>"}],
        "layout": {"shapes": [{"type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": 1, "y1": 1, "line": {"color": "#ae742a", "dash": "dot"}}]}
    }}}
    comparison = load_summary("comparison")
    ratios = comparison["timetable_ratio_by_hour"]
    comparison_time = [f'{row["hour"]:02}:00' for row in ratios]
    report["charts"]["timetable"] = {"title": "Observed travel time against the 2023 timetable", "views": {"all": {
        "label": "Matched stop pairs", "yTitle": "Observed / scheduled time",
        "note": "The timetable is from 2023 and assumes near-constant speed. This comparison describes two different snapshots, not punctuality against a current operating schedule.",
        "columns": ["Hour (IST)", "Median time ratio", "Traversals"],
        "rows": [[time, row["median_ratio"], row["traversals"]] for time, row in zip(comparison_time, ratios)],
        "traces": [{"type": "scatter", "mode": "lines+markers", "x": comparison_time, "y": [row["median_ratio"] for row in ratios], "name": "Median time ratio"}],
        "layout": {"shapes": [{"type": "line", "xref": "paper", "x0": 0, "x1": 1, "y0": 1, "y1": 1, "line": {"color": "#ae742a", "dash": "dot"}}]}
    }}}
    output = ROOT / "docs" / "report-data.js"
    output.write_text("window.REPORT = " + json.dumps(report, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Exported {len(report['charts'])} charts; no vehicle IDs, trips or individual positions exported.")


if __name__ == "__main__":
    main()
