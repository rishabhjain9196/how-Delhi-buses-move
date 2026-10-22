# Data

Nothing in this folder is committed. Run the scripts to recreate it.

| Folder | Contents | Source |
| --- | --- | --- |
| `raw/static_bus_archive/` | Delhi bus GTFS snapshot from early 2023 | [Mobility Database `mdb-1262`](https://files.mobilitydatabase.org/mdb-1262/latest.zip), originally from Delhi Open Transit Data |
| `raw/realtime/positions/` | Live bus positions, 21 October 2026, 6:23 pm to 12:23 am IST | Delhi Open Transit Data real-time API, which needs a personal key |
| `raw/realtime/poll_log.csv` | One row per poll: status, buses reported and feed timestamp | `scripts/collect_realtime.py` |
| `processed/` | Stop clusters, stop passages, rebuilt routes and route matches. The cleaned trajectories are not kept because they take about a minute to rebuild. | Project scripts |

**Source:** Department of Transport, Government of NCT of Delhi, and IIIT-Delhi, through [Delhi Open Transit Data](https://otd.delhi.gov.in/). Use is subject to the portal's [terms](https://otd.delhi.gov.in/static/assets/terms-and-conditions.pdf).
