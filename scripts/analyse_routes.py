"""Measure stop-to-stop travel times and bus bunching on the rebuilt routes.

Usage:
    python scripts/analyse_routes.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
FIGURES = ROOT / "docs" / "figures"
SUMMARY = ROOT / "docs" / "routes_summary.json"

MIN_TRAVERSALS = 10       # per segment, before it is ranked
MIN_RANK_DISTANCE_M = 250 # shorter segments are dominated by time spent at the stop
MAX_HOP_S = 600           # a single stop-to-stop hop longer than this is a halt, not traffic
BUNCHED_S = 120           # buses arriving within 2 minutes of each other count as bunched
MIN_BUSES_FOR_HEADWAY = 6
EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def load():
    events = pd.read_parquet(PROCESSED / "stop_events.parquet")
    events["trip_key"] = events.vehicle_id + "|" + events.trip_id + "|" + events.start_date
    routes = pd.read_parquet(PROCESSED / "routes.parquet")
    joined = events.merge(routes[["route_id", "stop_id", "seq"]], on=["route_id", "stop_id"])
    return joined, routes


def segments(joined, routes):
    """Travel time between consecutive rebuilt stops, for each trip that passed both."""
    df = joined.sort_values(["trip_key", "seq"])
    nxt = df.groupby("trip_key")[["seq", "stop_id", "arrival_ts"]].shift(-1)
    seg = df.assign(next_seq=nxt.seq, next_stop=nxt.stop_id, next_arrival=nxt.arrival_ts)
    # Only consecutive stops in the rebuilt order, travelled forwards in time.
    seg = seg[(seg.next_seq == seg.seq + 1) & (seg.next_arrival > seg.arrival_ts)].copy()
    seg["travel_s"] = seg.next_arrival - seg.arrival_ts
    coords = routes.drop_duplicates("stop_id").set_index("stop_id")[["stop_name", "stop_lat", "stop_lon"]]
    seg = seg.join(coords, on="stop_id").join(coords.add_prefix("next_"), on="next_stop")
    seg["distance_m"] = haversine_m(seg.stop_lat, seg.stop_lon, seg.next_stop_lat, seg.next_stop_lon)
    seg["speed_kmh"] = seg.distance_m / seg.travel_s * 3.6
    seg["hour"] = pd.to_datetime(seg.arrival_ts, unit="s", utc=True).dt.tz_convert("Asia/Kolkata").dt.hour
    seg = seg[(seg.speed_kmh < 80) & (seg.distance_m > 50)]
    halts = seg.travel_s > MAX_HOP_S
    return seg[~halts], int(halts.sum())


def segment_stats(seg):
    stats = seg.groupby(["stop_id", "next_stop"]).agg(
        from_stop=("stop_name", "first"), to_stop=("next_stop_name", "first"),
        lat=("stop_lat", "first"), lon=("stop_lon", "first"),
        next_lat=("next_stop_lat", "first"), next_lon=("next_stop_lon", "first"),
        distance_m=("distance_m", "first"), traversals=("travel_s", "size"),
        median_s=("travel_s", "median"), p90_s=("travel_s", lambda s: s.quantile(0.9)),
        routes=("route_id", "nunique"))
    stats["median_kmh"] = stats.distance_m / stats.median_s * 3.6
    stats["p90_to_median"] = stats.p90_s / stats.median_s
    return stats.reset_index()


def headways(joined):
    """Gaps between consecutive buses of the same route at the same stop."""
    df = joined.sort_values(["route_id", "stop_id", "arrival_ts"])
    df["gap_s"] = df.groupby(["route_id", "stop_id"]).arrival_ts.diff()
    df = df.dropna(subset=["gap_s"])
    # Ignore repeat matches of the same bus at the same stop.
    df = df[df.vehicle_id != df.groupby(["route_id", "stop_id"]).vehicle_id.shift()]
    by_stop = df.groupby(["route_id", "stop_id"]).agg(buses=("vehicle_id", "nunique"), median_gap_s=("gap_s", "median"),
                                                     cv=("gap_s", lambda s: s.std() / s.mean()),
                                                     bunched_share=("gap_s", lambda s: (s < BUNCHED_S).mean()))
    by_stop = by_stop[by_stop.buses >= MIN_BUSES_FOR_HEADWAY]
    by_route = by_stop.groupby("route_id").median().round(3)
    return df, by_route


def ranked_segments(stats):
    # Same-name pairs are turnarounds or opposite sides of one junction, not road segments.
    keep = (stats.traversals >= MIN_TRAVERSALS) & (stats.from_stop != stats.to_stop)
    return stats[keep & (stats.distance_m >= MIN_RANK_DISTANCE_M)]


def plot_segments(stats):
    ranked = ranked_segments(stats)
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    cmap = plt.get_cmap("RdYlGn")
    for row in ranked.sort_values("median_kmh", ascending=False).itertuples():
        colour = cmap(min(row.median_kmh, 30) / 30)
        ax.plot([row.lon, row.next_lon], [row.lat, row.next_lat], color=colour, linewidth=1.6)
    ax.set_aspect(1 / np.cos(np.radians(28.6)))
    ax.set_xlim(76.84, 77.42)
    ax.set_ylim(28.40, 28.90)
    ax.set_title(f"Median stop-to-stop speed ({len(ranked):,} segments of {MIN_RANK_DISTANCE_M}+ m with {MIN_TRAVERSALS}+ buses)")
    scalar = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, 30))
    fig.colorbar(scalar, ax=ax, shrink=0.7, label="Median speed (km/h, capped at 30)")
    fig.savefig(FIGURES / "segment_speeds.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def plot_headways(gaps):
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.hist(gaps.gap_s.clip(upper=3600) / 60, bins=60, color="#7c3aed")
    ax.axvline(BUNCHED_S / 60, color="#dc2626", linestyle="--", label="2-minute bunching threshold")
    ax.set_xlabel("Minutes between consecutive buses of the same route at a stop (capped at 60)")
    ax.set_ylabel("Gaps")
    ax.set_title("Observed headways")
    ax.legend(frameon=False)
    fig.savefig(FIGURES / "observed_headways.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    joined, routes = load()
    seg, halts = segments(joined, routes)
    stats = segment_stats(seg)
    gaps, by_route = headways(joined)
    plot_segments(stats)
    plot_headways(gaps)
    ranked = ranked_segments(stats)
    columns = ["from_stop", "to_stop", "distance_m", "traversals", "median_s", "median_kmh", "p90_to_median"]
    summary = {
        "segment_traversals": int(len(seg)),
        "halts_excluded": halts,
        "segments": int(len(stats)),
        "segments_ranked": int(len(ranked)),
        "median_segment_speed_kmh": round(float(seg.speed_kmh.median()), 1),
        "slowest_segments": ranked.nsmallest(10, "median_kmh")[columns].round(1).to_dict("records"),
        "most_variable_segments": ranked.nlargest(10, "p90_to_median")[columns].round(2).to_dict("records"),
        "headway_gaps": int(len(gaps)),
        "routes_with_headways": int(len(by_route)),
        "share_gaps_bunched": round(float((gaps.gap_s < BUNCHED_S).mean()), 3),
        "median_route_headway_cv": round(float(by_route.cv.median()), 2) if len(by_route) else None,
    }
    SUMMARY.write_text(json.dumps(summary, indent=2), "utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
