"""Explore the archived Delhi static GTFS feed and save summary figures.

Usage:
    python scripts/explore_static.py
"""

import json
import zipfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "raw" / "static_bus_archive" / "delhi_bus_gtfs_mdb-1262.zip"
FIGURES = ROOT / "docs" / "figures"
EARTH_RADIUS_M = 6_371_000


def load_feed(path):
    feed = zipfile.ZipFile(path)
    read = lambda name, **kwargs: pd.read_csv(feed.open(f"{name}.txt"), **kwargs)
    routes = read("routes", dtype=str)
    stops = read("stops", dtype={"stop_id": str})
    trips = read("trips", dtype=str)
    stop_times = read("stop_times", dtype={"trip_id": str, "stop_id": str})
    return routes, stops, trips, stop_times


def to_seconds(times):
    parts = times.str.split(":", expand=True).astype(int)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def build_segments(stops, stop_times):
    coords = stops.set_index("stop_id")[["stop_lat", "stop_lon"]]
    df = stop_times.join(coords, on="stop_id").sort_values(["trip_id", "stop_sequence"])
    df["seconds"] = to_seconds(df["arrival_time"])
    previous = df.groupby("trip_id")[["stop_lat", "stop_lon", "seconds"]].shift()
    df["distance_m"] = haversine_m(previous.stop_lat, previous.stop_lon, df.stop_lat, df.stop_lon)
    df["elapsed_s"] = df.seconds - previous.seconds
    segments = df.dropna(subset=["elapsed_s"])
    segments = segments[segments.elapsed_s > 0].copy()
    segments["speed_kmh"] = segments.distance_m / segments.elapsed_s * 3.6
    return df, segments


def add_trip_starts(trips):
    parts = trips.trip_id.str.extract(r"_(\d\d)_(\d\d)$").astype(float)
    trips = trips.copy()
    trips["start_min"] = parts[0] * 60 + parts[1]
    return trips


def headway_cv(trips):
    gaps = trips.sort_values(["route_id", "start_min"]).groupby("route_id").start_min.diff()
    grouped = gaps.groupby(trips.route_id)
    return (grouped.std() / grouped.mean()).dropna()


def save(fig, name):
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURES / name, dpi=130, bbox_inches="tight")
    plt.close(fig)


def plot_speeds(segments):
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.hist(segments.speed_kmh.clip(5, 30), bins=100, color="#2563eb")
    ax.set_yscale("log")
    ax.set_xlabel("Implied speed between consecutive stops (km/h)")
    ax.set_ylabel("Segments (log scale)")
    ax.set_title("Timetable times assume a constant 15 km/h")
    save(fig, "implied_speeds.png")


def plot_trips_by_hour(trips):
    counts = (trips.start_min // 60).value_counts().sort_index()
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.bar(counts.index, counts.values, color="#16a34a")
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("Hour of first departure")
    ax.set_ylabel("Trips")
    ax.set_title("Planned trip departures by hour")
    save(fig, "trips_by_hour.png")


def plot_headways(trips):
    gaps = trips.sort_values(["route_id", "start_min"]).groupby("route_id").start_min.diff().dropna()
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.hist(gaps.clip(upper=120), bins=range(0, 122, 2), color="#ea580c")
    ax.set_xlabel("Minutes between consecutive departures on a route (capped at 120)")
    ax.set_ylabel("Gaps")
    ax.set_title("Planned headways")
    save(fig, "planned_headways.png")


def plot_stop_map(stops, stop_times):
    daily = stop_times.groupby("stop_id").size().rename("visits")
    df = stops.join(daily, on="stop_id").fillna({"visits": 0}).sort_values("visits")
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    points = ax.scatter(df.stop_lon, df.stop_lat, c=np.log10(df.visits + 1), s=3, cmap="viridis")
    ax.set_aspect(1 / np.cos(np.radians(28.6)))
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Bus stops coloured by scheduled bus visits per day")
    fig.colorbar(points, ax=ax, shrink=0.7, label="log10(visits + 1)")
    save(fig, "stop_map.png")


def summarise(routes, stops, trips, stop_times, segments, cv):
    names = routes.route_long_name
    visits = stop_times.groupby("stop_id").size()
    busiest = visits.sort_values(ascending=False).head(10)
    stop_names = stops.set_index("stop_id").stop_name
    route_trips = trips.groupby("route_id").size()
    return {
        "routes": len(routes),
        "routes_by_agency": routes.agency_id.value_counts().to_dict(),
        "route_names_without_direction": int(names.str.replace(r"(UP|DOWN)$", "", regex=True).nunique()),
        "stops": len(stops),
        "stops_never_served": int(len(set(stops.stop_id) - set(stop_times.stop_id))),
        "trips": len(trips),
        "stop_times": len(stop_times),
        "implied_speed_kmh_p1_p50_p99": segments.speed_kmh.quantile([0.01, 0.5, 0.99]).round(2).tolist(),
        "zero_time_segments": int((stop_times.groupby("trip_id").seconds.diff() == 0).sum()),
        "stop_spacing_m_p50_p95_max": segments.distance_m.quantile([0.5, 0.95, 1.0]).round(0).tolist(),
        "trips_per_route_p25_p50_p75_max": route_trips.quantile([0.25, 0.5, 0.75, 1.0]).tolist(),
        "routes_with_regular_headways": int((cv == 0).sum()),
        "routes_with_headway_data": int(len(cv)),
        "busiest_stops": [
            {"stop": stop_names[stop_id], "visits_per_day": int(count)} for stop_id, count in busiest.items()
        ],
    }


def main():
    routes, stops, trips, stop_times = load_feed(FEED)
    stop_times, segments = build_segments(stops, stop_times)
    trips = add_trip_starts(trips)
    cv = headway_cv(trips)
    plot_speeds(segments)
    plot_trips_by_hour(trips)
    plot_headways(trips)
    plot_stop_map(stops, stop_times)
    summary = summarise(routes, stops, trips, stop_times, segments, cv)
    FIGURES.mkdir(parents=True, exist_ok=True)
    (ROOT / "docs" / "static_summary.json").write_text(json.dumps(summary, indent=2), "utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
