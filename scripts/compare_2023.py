"""Compare the evening of 21 October 2026 with the 2023 timetable.

1. Match each rebuilt live route to the 2023 route that shares most of its stops.
2. Compare 2023 scheduled stop-to-stop times with observed times.
3. Compare 2023 planned evening departures with observed trips on matched routes.
4. Find 2023 stops no longer served and busy areas far from any 2023 stop.

Usage:
    python scripts/compare_2023.py
"""

import json
import sys
import zipfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyse_routes

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
FEED = ROOT / "data" / "raw" / "static_bus_archive" / "delhi_bus_gtfs_mdb-1262.zip"
FIGURES = ROOT / "docs" / "figures"
SUMMARY = ROOT / "docs" / "comparison_summary.json"

STRONG_SHARE = 0.7        # share of a live route's stops found on one 2023 route
STRONG_JACCARD = 0.5
PARTIAL_SHARE = 0.5
FREQUENCY_HOURS = range(19, 23)   # fully inside the collection window
NEW_AREA_M = 500          # bus activity this far from any 2023 stop suggests a new corridor
CELL_DEG = 0.004
LAT0 = 28.6


def load_2023():
    feed = zipfile.ZipFile(FEED)
    routes = pd.read_csv(feed.open("routes.txt"), dtype=str)
    trips = pd.read_csv(feed.open("trips.txt"), dtype=str)
    times = pd.read_csv(feed.open("stop_times.txt"), dtype={"trip_id": str, "stop_id": str},
                        usecols=["trip_id", "stop_id", "stop_sequence", "arrival_time"])
    clusters = pd.read_parquet(PROCESSED / "stop_cluster_map.parquet")
    one_trip = trips.drop_duplicates("route_id")[["route_id", "trip_id"]]
    seq = times.merge(one_trip, on="trip_id").merge(clusters, on="stop_id").sort_values(["route_id", "stop_sequence"])
    parts = seq.arrival_time.str.split(":", expand=True).astype(int)
    seq["seconds"] = parts[0] * 3600 + parts[1] * 60 + parts[2]
    start = trips.trip_id.str.extract(r"_(\d\d)_(\d\d)$").astype(int)
    trips["start_hour"] = start[0]
    return routes, trips, seq


def match_routes(seq23, routes23):
    live = pd.read_parquet(PROCESSED / "routes.parquet")
    sets23 = seq23.groupby("route_id").cluster_id.apply(set)
    index = {}
    for route, stops in sets23.items():
        for stop in stops:
            index.setdefault(stop, []).append(route)
    rows = []
    for route, stops in live.groupby("route_id").stop_id.apply(set).items():
        hits = {}
        for stop in stops:
            for candidate in index.get(stop, []):
                hits[candidate] = hits.get(candidate, 0) + 1
        if not hits:
            rows.append({"live_route": route, "live_stops": len(stops)})
            continue
        # Ties go to the route with more shared stops, then to the lowest route ID, so results are repeatable.
        best = max(hits, key=lambda r: (hits[r] / len(stops | sets23[r]), hits[r], -int(r)))
        shared = hits[best]
        rows.append({"live_route": route, "live_stops": len(stops), "route23": best,
                     "share_of_live": shared / len(stops), "share_of_2023": shared / len(sets23[best]),
                     "jaccard": shared / len(stops | sets23[best])})
    matches = pd.DataFrame(rows).merge(routes23[["route_id", "route_long_name"]], left_on="route23",
                                       right_on="route_id", how="left").drop(columns="route_id")
    strong = (matches.share_of_live >= STRONG_SHARE) & (matches.jaccard >= STRONG_JACCARD)
    partial = matches.share_of_live >= PARTIAL_SHARE
    matches["tier"] = np.select([strong, partial], ["strong", "partial"], "none")
    matches.to_parquet(PROCESSED / "route_matches.parquet", index=False)
    return matches


def timetable_vs_observed(seq23):
    """Observed stop-to-stop times divided by the 2023 timetable's times, for the same stop pairs."""
    nxt = seq23.groupby("route_id")[["cluster_id", "seconds"]].shift(-1)
    pairs = seq23.assign(next_stop=nxt.cluster_id, scheduled_s=nxt.seconds - seq23.seconds)
    pairs = pairs[(pairs.next_stop.notna()) & (pairs.cluster_id != pairs.next_stop) & (pairs.scheduled_s > 0)]
    scheduled = pairs.groupby(["cluster_id", "next_stop"]).scheduled_s.median().rename("scheduled_s")
    joined, routes = analyse_routes.load()
    seg, _ = analyse_routes.segments(joined, routes)
    seg = seg.join(scheduled, on=["stop_id", "next_stop"], how="inner")
    seg["ratio"] = seg.travel_s / seg.scheduled_s
    hourly = seg.groupby("hour").agg(median_ratio=("ratio", "median"), share_slower=("ratio", lambda r: (r > 1).mean()),
                                     traversals=("ratio", "size"))
    order = sorted(hourly.index, key=lambda h: (h < 12, h))
    return seg, hourly.loc[order]


def frequency_vs_2023(matches, trips23):
    """Planned 2023 departures against observed trip starts, 19:00 to 23:00, for strongly matched routes."""
    events = pd.read_parquet(PROCESSED / "stop_events.parquet", columns=["vehicle_id", "trip_id", "route_id", "start_date", "start_time"])
    events["hour"] = events.start_time.str[:2].astype(int)
    observed = (events[events.hour.isin(FREQUENCY_HOURS)].drop_duplicates(["vehicle_id", "trip_id", "start_date"])
                .groupby("route_id").size().rename("observed_trips"))
    planned = trips23[trips23.start_hour.isin(FREQUENCY_HOURS)].groupby("route_id").size().rename("planned_trips")
    strong = matches[matches.tier == "strong"]
    df = strong.join(observed, on="live_route").join(planned, on="route23")
    df = df.fillna({"observed_trips": 0, "planned_trips": 0})
    df = df[df.planned_trips > 0]
    df["ratio"] = df.observed_trips / df.planned_trips
    return df


def network_change(trajectories=None):
    clusters = pd.read_parquet(PROCESSED / "stop_directions.parquet")
    passes = pd.read_parquet(PROCESSED / "stop_events.parquet", columns=["stop_id", "vehicle_id"])
    buses = passes.groupby("stop_id").vehicle_id.nunique()
    clusters["buses"] = clusters.stop_id.map(buses).fillna(0)
    if trajectories is None:
        trajectories = pd.read_parquet(PROCESSED / "trajectories.parquet", columns=["vehicle_id", "lat", "lon", "step"])
    steps = trajectories.loc[trajectories.step == "ok", ["vehicle_id", "lat", "lon"]]
    steps = steps.assign(cx=np.floor(steps.lon / CELL_DEG).astype(int), cy=np.floor(steps.lat / CELL_DEG).astype(int))
    cells = steps.groupby(["cx", "cy"]).vehicle_id.nunique().rename("buses").reset_index()
    cells = cells[cells.buses >= 5]
    cells["lat"], cells["lon"] = (cells.cy + 0.5) * CELL_DEG, (cells.cx + 0.5) * CELL_DEG
    scale = np.array([111_320 * np.cos(np.radians(LAT0)), 110_540])
    tree = cKDTree(clusters[["stop_lon", "stop_lat"]].values * scale)
    cells["nearest_stop_m"], _ = tree.query(cells[["lon", "lat"]].values * scale)
    return clusters, cells


def plot_timetable(hourly):
    fig, ax = plt.subplots(figsize=(8, 3.6))
    labels = [f"{h:02d}:00" for h in hourly.index]
    ax.bar(labels, hourly.median_ratio, color=["#dc2626" if r > 1 else "#16a34a" for r in hourly.median_ratio])
    ax.axhline(1, color="#334155", linewidth=1)
    for i, r in enumerate(hourly.median_ratio):
        ax.text(i, r + 0.03, f"{r:.2f}", ha="center", fontsize=9)
    ax.set_ylabel("Observed time / 2023 timetable time")
    ax.set_xlabel("Hour starting (IST)")
    ax.set_title("How the 2023 timetable's stop-to-stop times compare with reality")
    fig.savefig(FIGURES / "timetable_vs_observed.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def plot_frequency(freq):
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.hist(freq.ratio.clip(upper=3), bins=np.arange(0, 3.05, 0.1), color="#2563eb")
    ax.axvline(1, color="#334155", linestyle="--", label="Same as 2023 plan")
    ax.set_xlabel("Observed trips / 2023 planned trips, 19:00 to 23:00 (capped at 3)")
    ax.set_ylabel("Matched routes")
    ax.set_title(f"Evening service on {len(freq)} routes matched to the 2023 timetable")
    ax.legend(frameon=False)
    fig.savefig(FIGURES / "frequency_vs_2023.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def plot_network(clusters, cells):
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    served = clusters[clusters.buses >= 3]
    unserved = clusters[clusters.buses < 3]
    new = cells[cells.nearest_stop_m > NEW_AREA_M]
    ax.scatter(served.stop_lon, served.stop_lat, s=2, color="#94a3b8", label=f"2023 stops passed ({len(served):,})")
    ax.scatter(unserved.stop_lon, unserved.stop_lat, s=6, color="#dc2626", label=f"2023 stops not passed ({len(unserved):,})")
    ax.scatter(new.lon, new.lat, s=10, marker="s", color="#2563eb", label=f"Bus areas over {NEW_AREA_M} m from a 2023 stop ({len(new):,})")
    ax.set_aspect(1 / np.cos(np.radians(LAT0)))
    ax.set_xlim(76.84, 77.42)
    ax.set_ylim(28.40, 28.90)
    ax.set_title("Network change since 2023: evening of 21 October 2026")
    ax.legend(frameon=False, loc="lower left", fontsize=8)
    fig.savefig(FIGURES / "network_change.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def fleet(trajectories=None):
    if trajectories is None:
        trajectories = pd.read_parquet(PROCESSED / "trajectories.parquet", columns=["vehicle_id"])
    buses = trajectories.vehicle_id.drop_duplicates()
    series = buses.str.extract(r"^(DL\d+[A-Z]+)")[0].fillna("other")
    return series.value_counts().to_dict(), len(buses)


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    routes23, trips23, seq23 = load_2023()
    matches = match_routes(seq23, routes23)
    seg, hourly = timetable_vs_observed(seq23)
    freq = frequency_vs_2023(matches, trips23)
    clusters, cells = network_change()
    plot_timetable(hourly)
    plot_frequency(freq)
    plot_network(clusters, cells)
    series, buses = fleet()
    top = matches[matches.tier == "strong"].nlargest(10, "jaccard")
    summary = {
        "live_routes": int(len(matches)),
        "match_tiers": matches.tier.value_counts().to_dict(),
        "share_of_live_quantiles": matches.share_of_live.quantile([0.25, 0.5, 0.75]).round(2).tolist(),
        "best_matches": top[["live_route", "route_long_name", "share_of_live", "share_of_2023", "jaccard"]].round(2).to_dict("records"),
        "timetable_pairs_compared": int(seg[["stop_id", "next_stop"]].drop_duplicates().shape[0]),
        "timetable_traversals_compared": int(len(seg)),
        "timetable_ratio_by_hour": hourly.round(2).reset_index().to_dict("records"),
        "timetable_ratio_overall": round(float(seg.ratio.median()), 2),
        "frequency_routes": int(len(freq)),
        "frequency_ratio_quantiles": freq.ratio.quantile([0.25, 0.5, 0.75]).round(2).tolist(),
        "frequency_totals": {"planned_2023": int(freq.planned_trips.sum()), "observed_2026": int(freq.observed_trips.sum())},
        "frequency_share_below_half": round(float((freq.ratio < 0.5).mean()), 3),
        "frequency_share_above_plan": round(float((freq.ratio > 1).mean()), 3),
        "stops_2023_clusters": int(len(clusters)),
        "stops_passed_by_3_buses": int((clusters.buses >= 3).sum()),
        "bus_cells": int(len(cells)),
        "bus_cells_far_from_2023_stops": int((cells.nearest_stop_m > NEW_AREA_M).sum()),
        "plate_series": series,
        "buses": buses,
    }
    SUMMARY.write_text(json.dumps(summary, indent=2), "utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "best_matches"}, indent=2))


if __name__ == "__main__":
    main()
