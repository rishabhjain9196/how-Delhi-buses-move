"""Rebuild the stop sequence of each live route from observed stop passages.

The live feed's route IDs do not match any published timetable. Each live route's stops are the
stops its buses actually pass, ordered by the median time since the trip started.

Usage:
    python scripts/build_routes.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "data" / "processed" / "stop_events.parquet"
STOPS = ROOT / "data" / "processed" / "stop_directions.parquet"
OUT = ROOT / "data" / "processed" / "routes.parquet"

MIN_TRIPS_PER_STOP = 2
MIN_SHARE_OF_TRIPS = 0.3
MIN_STOPS_PER_ROUTE = 5


def load_events():
    events = pd.read_parquet(EVENTS)
    start = pd.to_datetime(events.start_date + " " + events.start_time, format="%Y%m%d %H:%M:%S")
    epoch = pd.Timestamp("1970-01-01", tz="UTC")
    events["start_ts"] = (start.dt.tz_localize("Asia/Kolkata") - epoch).dt.total_seconds()
    events["elapsed_s"] = events.arrival_ts - events.start_ts
    events["trip_key"] = events.vehicle_id + "|" + events.trip_id + "|" + events.start_date
    return events[events.elapsed_s >= 0]


def build(events):
    trips_per_route = events.groupby("route_id").trip_key.nunique().rename("route_trips")
    stops = events.groupby(["route_id", "stop_id"]).agg(trips=("trip_key", "nunique"),
                                                        median_elapsed_s=("elapsed_s", "median")).reset_index()
    stops = stops.join(trips_per_route, on="route_id")
    keep = (stops.trips >= MIN_TRIPS_PER_STOP) & (stops.trips >= MIN_SHARE_OF_TRIPS * stops.route_trips)
    stops = stops[keep].sort_values(["route_id", "median_elapsed_s"])
    stops["seq"] = stops.groupby("route_id").cumcount()
    size = stops.groupby("route_id").stop_id.transform("size")
    return stops[size >= MIN_STOPS_PER_ROUTE].reset_index(drop=True)


def order_agreement(events, routes):
    """Spearman correlation between each trip's actual stop order and its route's rebuilt order."""
    joined = events.merge(routes[["route_id", "stop_id", "seq"]], on=["route_id", "stop_id"])
    scores = []
    for _, trip in joined.groupby("trip_key"):
        if len(trip) >= 4 and trip.seq.nunique() > 1 and trip.arrival_ts.nunique() > 1:
            scores.append(trip.arrival_ts.rank().corr(trip.seq.rank()))
    return pd.Series(scores)


def main():
    events = load_events()
    routes = build(events)
    names = pd.read_parquet(STOPS)[["stop_id", "stop_name", "stop_lat", "stop_lon"]]
    routes = routes.merge(names, on="stop_id", how="left")
    routes.to_parquet(OUT, index=False)
    agreement = order_agreement(events, routes)
    print(f"live routes seen: {events.route_id.nunique():,}  rebuilt with {MIN_STOPS_PER_ROUTE}+ stops: {routes.route_id.nunique():,}")
    print("stops per rebuilt route:", routes.groupby("route_id").size().describe(percentiles=[0.5, 0.9]).round(1).to_dict())
    print("trip order agreement (Spearman):", agreement.describe(percentiles=[0.1, 0.5]).round(3).to_dict())
    sample = routes[routes.route_id == routes.route_id.value_counts().idxmax()]
    print(f"\nexample route {sample.route_id.iloc[0]}:")
    print(sample[["seq", "stop_name", "trips", "median_elapsed_s"]].head(12).to_string(index=False))


if __name__ == "__main__":
    main()
