"""Detect when each bus passes each stop.

Each movement step is projected onto nearby stops. A stop counts as passed when the step comes
within MATCH_M of it while heading the same way the stop serves.

Stop locations and directions come from the 2023 timetable, the newest one available. The live
feed's own route IDs do not match that timetable, so routes are rebuilt from these events later.

Usage:
    python scripts/match_stops.py
"""

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "data" / "raw" / "static_bus_archive" / "delhi_bus_gtfs_mdb-1262.zip"
TRAJECTORIES = ROOT / "data" / "processed" / "trajectories.parquet"
OUT = ROOT / "data" / "processed" / "stop_events.parquet"

MATCH_M = 35            # how close the path must pass to a stop cluster
MAX_HEADING_DIFF = 60   # degrees between bus heading and stop direction
MOVING_M = 15           # steps shorter than this give no reliable heading
CLUSTER_M = 60          # stops closer than this, facing the same way, are one stop
LAT0 = 28.6


def to_xy(lat, lon):
    return np.column_stack([lon * 111_320 * np.cos(np.radians(LAT0)), lat * 110_540])


def bearing(dx, dy):
    return np.degrees(np.arctan2(dx, dy)) % 360


def angle_diff(a, b):
    return np.abs((a - b + 180) % 360 - 180)


def stop_directions():
    """Typical direction of travel at each stop, from its neighbours in 2023 trips."""
    feed = zipfile.ZipFile(FEED)
    stops = pd.read_csv(feed.open("stops.txt"), dtype={"stop_id": str})
    trips = pd.read_csv(feed.open("trips.txt"), dtype=str)
    # Every trip on a route visits the same stops in the same order, so one trip per route is enough.
    sample = set(trips.drop_duplicates("route_id").trip_id)
    times = pd.read_csv(feed.open("stop_times.txt"), dtype={"trip_id": str, "stop_id": str},
                        usecols=["trip_id", "stop_id", "stop_sequence"])
    times = times[times.trip_id.isin(sample)].sort_values(["trip_id", "stop_sequence"])
    times = times[times.groupby("trip_id").trip_id.transform("size") > 1]
    xy = pd.DataFrame(to_xy(stops.stop_lat.values, stops.stop_lon.values), columns=["x", "y"], index=stops.stop_id)
    times = times.join(xy, on="stop_id")
    group = times.groupby("trip_id")
    prev_xy = group[["x", "y"]].shift()
    next_xy = group[["x", "y"]].shift(-1)
    # Use the next stop where possible, and the previous stop at the end of a trip.
    dx = next_xy.x.fillna(times.x) - prev_xy.x.fillna(times.x)
    dy = next_xy.y.fillna(times.y) - prev_xy.y.fillna(times.y)
    times["sin"], times["cos"] = np.sin(np.arctan2(dx, dy)), np.cos(np.arctan2(dx, dy))
    direction = times.groupby("stop_id")[["sin", "cos"]].mean()
    stops = stops.join(direction, on="stop_id").dropna(subset=["sin"])
    stops["direction"] = bearing(stops.sin, stops.cos)
    stops[["x", "y"]] = to_xy(stops.stop_lat.values, stops.stop_lon.values)
    return stops[["stop_id", "stop_name", "stop_lat", "stop_lon", "x", "y", "direction"]].reset_index(drop=True)


def cluster_stops(stops):
    """Merge duplicate stop records: same side of the road and within CLUSTER_M of each other."""
    tree = cKDTree(stops[["x", "y"]].values)
    parent = np.arange(len(stops))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in tree.query_pairs(CLUSTER_M):
        if angle_diff(stops.direction[i], stops.direction[j]) <= MAX_HEADING_DIFF:
            parent[root(i)] = root(j)
    stops = stops.assign(cluster=[root(i) for i in range(len(stops))])
    names = stops.groupby("cluster").stop_name.agg(lambda s: s.mode().iloc[0])
    angles = np.radians(stops.direction)
    clusters = stops.assign(sin=np.sin(angles), cos=np.cos(angles)).groupby("cluster").agg(
        stop_lat=("stop_lat", "mean"), stop_lon=("stop_lon", "mean"), sin=("sin", "mean"), cos=("cos", "mean"),
        members=("stop_id", "size"), first_id=("stop_id", "min"))
    clusters["stop_name"] = names
    clusters["direction"] = bearing(clusters.sin, clusters.cos)
    # Cluster IDs reuse the lowest original stop ID in the cluster so they stay readable.
    clusters["stop_id"] = "c" + clusters.first_id
    clusters[["x", "y"]] = to_xy(clusters.stop_lat.values, clusters.stop_lon.values)
    columns = ["stop_id", "stop_name", "stop_lat", "stop_lon", "x", "y", "direction", "members"]
    members = stops[["stop_id", "cluster"]].join(clusters.stop_id.rename("cluster_id"), on="cluster")
    members[["stop_id", "cluster_id"]].to_parquet(ROOT / "data" / "processed" / "stop_cluster_map.parquet", index=False)
    return clusters[columns].reset_index(drop=True)


def add_headings(df):
    xy = to_xy(df.lat.values, df.lon.values)
    df["x"], df["y"] = xy[:, 0], xy[:, 1]
    prev = df.groupby("vehicle_id")[["x", "y", "vehicle_ts"]].shift()
    df["x0"], df["y0"], df["ts0"] = prev.x, prev.y, prev.vehicle_ts
    heading = bearing(df.x - df.x0, df.y - df.y0).where(df.dist_m >= MOVING_M)
    # Standing buses keep the heading of their last movement.
    df["heading"] = heading.groupby(df.vehicle_id).ffill()
    return df


def match(steps, stops):
    tree = cKDTree(stops[["x", "y"]].values)
    a = steps[["x0", "y0"]].values
    b = steps[["x", "y"]].values
    mid = (a + b) / 2
    radius = np.hypot(*(b - a).T) / 2 + MATCH_M
    candidates = tree.query_ball_point(mid, radius)
    step_idx = np.repeat(np.arange(len(steps)), [len(c) for c in candidates])
    stop_idx = np.concatenate([np.asarray(c, dtype=int) for c in candidates])
    a, b = a[step_idx], b[step_idx]
    s = stops[["x", "y"]].values[stop_idx]
    ab = b - a
    length_sq = (ab ** 2).sum(axis=1)
    t = np.clip(np.where(length_sq > 0, ((s - a) * ab).sum(axis=1) / np.where(length_sq > 0, length_sq, 1), 0), 0, 1)
    distance = np.hypot(*(a + t[:, None] * ab - s).T)
    events = pd.DataFrame({
        "row": steps.index.values[step_idx],
        "stop_id": stops.stop_id.values[stop_idx],
        "distance_m": distance,
        "pass_ts": steps.ts0.values[step_idx] + t * steps.dt_s.values[step_idx],
        "heading_diff": angle_diff(steps.heading.values[step_idx], stops.direction.values[stop_idx]),
    })
    return events[(events.distance_m <= MATCH_M) & (events.heading_diff <= MAX_HEADING_DIFF)]


def main():
    stops = cluster_stops(stop_directions())
    stops.to_parquet(ROOT / "data" / "processed" / "stop_directions.parquet", index=False)
    df = pd.read_parquet(TRAJECTORIES)
    df = add_headings(df)
    steps = df[(df.step == "ok") & df.heading.notna()]
    events = match(steps, stops)
    events = events.join(df[["vehicle_id", "trip_id", "route_id", "start_date", "start_time"]], on="row")
    # A bus waiting at a stop matches it several times: keep its arrival and departure.
    keys = ["vehicle_id", "trip_id", "route_id", "start_date", "start_time", "stop_id"]
    events = events.groupby(keys, as_index=False).agg(
        arrival_ts=("pass_ts", "min"), departure_ts=("pass_ts", "max"), distance_m=("distance_m", "min"))
    events["dwell_s"] = events.departure_ts - events.arrival_ts
    events.to_parquet(OUT, index=False)
    print(f"stop clusters: {len(stops):,} (from {int(stops.members.sum()):,} stop records)")
    print(f"stop passages: {len(events):,}  from {events.trip_id.nunique():,} trips and {events.stop_id.nunique():,} stops")
    print("passages per trip:", events.groupby("trip_id").size().describe(percentiles=[0.5, 0.9]).round(1).to_dict())
    print("dwell seconds:", events.dwell_s.describe(percentiles=[0.5, 0.9]).round(0).to_dict())


if __name__ == "__main__":
    main()
