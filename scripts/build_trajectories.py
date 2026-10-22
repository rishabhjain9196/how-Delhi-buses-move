"""Turn raw live positions into cleaned bus trajectories with computed speeds.

The feed's speed field is always 0, so speed comes from consecutive positions.

Usage:
    python scripts/build_trajectories.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "realtime" / "positions"
OUT = ROOT / "data" / "processed" / "trajectories.parquet"

EARTH_RADIUS_M = 6_371_000
MAX_SPEED_KMH = 80      # faster implies a GPS jump
MAX_GAP_S = 120         # longer gaps are not used for speed
LAYOVER_S = 300         # a bus that stays within LAYOVER_M for this long is parked, not in traffic
LAYOVER_M = 60          # allows for GPS jitter while parked
MAX_STALE_S = 300       # positions older than this when published are dropped


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def longest_collection_run(max_break_s=60):
    """Start and end of the longest stretch of polling without a break."""
    log = pd.read_csv(ROOT / "data" / "raw" / "realtime" / "poll_log.csv")
    times = log.polled_at.sort_values().reset_index(drop=True)
    run = (times.diff() > max_break_s).cumsum()
    spans = times.groupby(run).agg(["min", "max"])
    longest = (spans["max"] - spans["min"]).idxmax()
    return spans.loc[longest, "min"], spans.loc[longest, "max"]


def load_positions():
    df = pd.read_parquet(RAW)
    start, end = longest_collection_run()
    df = df[df.polled_at.between(start, end)]
    df = df[(df.vehicle_id != "") & (df.lat != 0) & (df.lon != 0)]
    df = df[(df.feed_ts - df.vehicle_ts).between(-120, MAX_STALE_S)]
    df = df.drop_duplicates(["vehicle_id", "vehicle_ts"])
    return df.sort_values(["vehicle_id", "vehicle_ts"]).reset_index(drop=True)


def add_steps(df):
    previous = df.groupby("vehicle_id")[["lat", "lon", "vehicle_ts", "trip_id"]].shift()
    df["dt_s"] = df.vehicle_ts - previous.vehicle_ts
    df["dist_m"] = haversine_m(previous.lat, previous.lon, df.lat, df.lon)
    df["speed_kmh"] = df.dist_m / df.dt_s * 3.6
    df["same_trip"] = df.trip_id == previous.trip_id
    return df


def displacement_over(df, seconds):
    """Distance from each position to the same bus's position `seconds` later (NaN if not observed)."""
    left = df[["vehicle_id", "vehicle_ts", "lat", "lon"]].assign(target=df.vehicle_ts + seconds)
    right = df[["vehicle_id", "vehicle_ts", "lat", "lon"]].rename(
        columns={"vehicle_ts": "later_ts", "lat": "later_lat", "lon": "later_lon"})
    merged = pd.merge_asof(left.sort_values("target"), right.sort_values("later_ts"), left_on="target",
                           right_on="later_ts", by="vehicle_id", direction="backward").set_index(left.sort_values("target").index)
    covered = merged.later_ts >= merged.vehicle_ts + 0.8 * seconds
    distance = haversine_m(merged.lat, merged.lon, merged.later_lat, merged.later_lon)
    return distance.where(covered).reindex(df.index)


def mark_layovers(df):
    # A position is parked if the bus stays within LAYOVER_M for LAYOVER_S, looking forward or back.
    forward = displacement_over(df, LAYOVER_S) < LAYOVER_M
    last_start = df.vehicle_ts.where(forward).groupby(df.vehicle_id).ffill()
    within = (df.vehicle_ts - last_start) <= LAYOVER_S
    df["layover"] = forward | within
    return df


def classify(df):
    df["step"] = "ok"
    df.loc[df.dt_s.isna(), "step"] = "first"
    df.loc[~df.same_trip & df.dt_s.notna(), "step"] = "new_trip"
    df.loc[(df.step == "ok") & (df.dt_s > MAX_GAP_S), "step"] = "gap"
    df.loc[(df.step == "ok") & (df.speed_kmh > MAX_SPEED_KMH), "step"] = "jump"
    df.loc[(df.step == "ok") & df.layover, "step"] = "layover"
    return df


def main():
    df = classify(mark_layovers(add_steps(load_positions())))
    df["time"] = pd.to_datetime(df.vehicle_ts, unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"positions: {len(df):,}  buses: {df.vehicle_id.nunique():,}  trips: {df.trip_id.nunique():,}")
    print(f"time span: {df.time.min():%Y-%m-%d %H:%M} to {df.time.max():%H:%M}")
    print("step types:", df.step.value_counts().to_dict())
    ok = df[df.step == "ok"]
    print("speed of usable steps (km/h):", ok.speed_kmh.describe(percentiles=[0.1, 0.5, 0.9]).round(1).to_dict())


if __name__ == "__main__":
    main()
