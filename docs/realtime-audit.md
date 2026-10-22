# Live feed audit

- **Date:** 21 October 2026, 5:12 pm to 5:26 pm IST.
- **Method:** Polled the GTFS-Realtime vehicle positions feed every 10 seconds for 12 minutes with `scripts/collect_realtime.py`.

## Results

| Check | Result |
| --- | --- |
| Buses seen | 5,218, of which 4,574 moved more than 100 m in 10 minutes |
| Routes and trips seen | 1,358 route IDs and 5,621 trip IDs |
| Feed refresh interval | 11 to 12 seconds |
| Position update gap per bus | Median 11 s, 90th percentile 22 s |
| Position age at publication | Median 21 s, 90th percentile 150 s |
| Fields present on every bus | Trip ID, route ID, trip start time and date, bus ID, latitude, longitude, timestamp |
| Speed and bearing | Always 0, so both must be computed from consecutive positions |
| Trip type | 65% `ADDED` (not in the schedule) and 35% `SCHEDULED` |
| Empty responses | 6 of 69 polls returned no buses |
| Storage | About 0.35 to 0.5 GB per day as Parquet, keeping only changed positions |

## Problem: live route IDs do not match the 2023 timetable

- Only 634 of the 1,358 live route IDs exist in the archived timetable.
- Where they exist, they point to the wrong roads.
    - Only 3.8% of buses were within 300 m of a stop on their claimed archived route.
    - The same check with randomly assigned routes gives 4.0%.
- Only 50 of 5,621 live trip IDs exist in the archive.
- **Conclusion:** The live feed uses a newer route table that is not publicly downloadable.

## Resolution

- Each live route's stop order was rebuilt from the stops its buses actually passed, using the 2023 stop locations (`scripts/build_routes.py`).
- 1,421 routes were rebuilt with a median of 31 stops. In the median trip, buses passed the stops in the rebuilt order (rank agreement 0.99).
- 368 rebuilt routes match a 2023 route strongly by their stops, which recovers their 2023 route names (`scripts/compare_2023.py`).

## Notes

- **Bus IDs are licence plates.** They identify buses, not people. Published outputs show only counts by registration series, never individual plates, to stay well clear of the terms' ban on tracking individuals.
- **Position timestamps can be slightly ahead of the feed timestamp,** by up to 111 seconds, which suggests clock differences on some devices.
