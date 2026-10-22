"""Collect Delhi live bus positions from the Open Transit Data GTFS-Realtime feed.

The API key is read from the OTD_API_KEY environment variable or from a local .env file.

Usage:
    python scripts/collect_realtime.py --minutes 10 --interval 10
    python scripts/collect_realtime.py --hours 48 --interval 30
"""

import argparse
import csv
import gzip
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from google.transit import gtfs_realtime_pb2

ROOT = Path(__file__).resolve().parent.parent
URL = "https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb"
OUT = ROOT / "data" / "raw" / "realtime"
FLUSH_EVERY = 20


def api_key():
    if os.environ.get("OTD_API_KEY"):
        return os.environ["OTD_API_KEY"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("OTD_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise SystemExit("Set OTD_API_KEY or add it to .env.")


def parse(content, polled_at):
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(content)
    rows = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        rows.append({
            "polled_at": polled_at,
            "feed_ts": feed.header.timestamp,
            "vehicle_ts": v.timestamp,
            "vehicle_id": v.vehicle.id,
            "trip_id": v.trip.trip_id,
            "route_id": v.trip.route_id,
            "start_time": v.trip.start_time,
            "start_date": v.trip.start_date,
            "schedule_relationship": v.trip.schedule_relationship,
            "lat": v.position.latitude,
            "lon": v.position.longitude,
            "speed": v.position.speed,
            "bearing": v.position.bearing,
        })
    return feed.header.timestamp, rows


def flush(rows):
    if not rows:
        return
    df = pd.DataFrame(rows)
    day = datetime.fromtimestamp(rows[0]["polled_at"]).strftime("%Y%m%d")
    folder = OUT / "positions" / f"date={day}"
    folder.mkdir(parents=True, exist_ok=True)
    df.to_parquet(folder / f"part-{rows[0]['polled_at']}.parquet", index=False)
    rows.clear()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=0)
    parser.add_argument("--hours", type=float, default=0)
    parser.add_argument("--interval", type=float, default=10, help="seconds between polls; the feed refreshes about every 11 s")
    parser.add_argument("--keep-raw", action="store_true", help="also save each raw response")
    args = parser.parse_args()
    duration = args.minutes * 60 + args.hours * 3600 or 600
    key = api_key()
    OUT.mkdir(parents=True, exist_ok=True)
    log_path = OUT / "poll_log.csv"
    new_log = not log_path.exists()
    session = requests.Session()
    session.headers["User-Agent"] = "delhi-bus-research/0.1"
    rows, last_feed_ts, last_seen, polls = [], None, {}, 0
    end = time.time() + duration
    with open(log_path, "a", newline="") as log_file:
        log = csv.writer(log_file)
        if new_log:
            log.writerow(["polled_at", "status", "bytes", "feed_ts", "vehicles", "new_feed", "error"])
        while time.time() < end:
            started = time.time()
            polled_at = int(started)
            status, size, feed_ts, vehicles, new_feed, error = 0, 0, "", 0, False, ""
            try:
                response = session.get(URL, params={"key": key}, timeout=60)
                status, size = response.status_code, len(response.content)
                if status == 200:
                    feed_ts, batch = parse(response.content, polled_at)
                    vehicles = len(batch)
                    # The feed sometimes returns an empty message; treat it as a failed poll.
                    if not batch:
                        error = "empty_feed"
                    new_feed = bool(batch) and feed_ts != last_feed_ts
                    if new_feed:
                        # Keep only positions that changed since the last poll.
                        fresh = [r for r in batch if last_seen.get(r["vehicle_id"]) != r["vehicle_ts"]]
                        last_seen.update((r["vehicle_id"], r["vehicle_ts"]) for r in fresh)
                        rows.extend(fresh)
                        last_feed_ts = feed_ts
                        if args.keep_raw:
                            raw = OUT / "pb" / datetime.fromtimestamp(polled_at).strftime("%Y%m%d")
                            raw.mkdir(parents=True, exist_ok=True)
                            with gzip.open(raw / f"{polled_at}.pb.gz", "wb") as f:
                                f.write(response.content)
            except (requests.RequestException, ValueError) as exc:
                error = type(exc).__name__
            log.writerow([polled_at, status, size, feed_ts, vehicles, new_feed, error])
            log_file.flush()
            polls += 1
            print(f"{datetime.fromtimestamp(polled_at):%H:%M:%S} status={status} vehicles={vehicles} new={new_feed} {error}", flush=True)
            if polls % FLUSH_EVERY == 0:
                flush(rows)
            time.sleep(max(0, args.interval - (time.time() - started)))
    flush(rows)


if __name__ == "__main__":
    main()
