# How Delhi's Buses Move

Six hours of live GPS from more than 6,000 Delhi city buses, turned into maps of busy and free roads, bunching patterns and an arrival-time model.

**[Read the visual report](https://rishabhjain9196.github.io/how-Delhi-buses-move/)** &nbsp;|&nbsp; **[Open the notebook](notebooks/delhi_bus_analysis.ipynb)** &nbsp;|&nbsp; **[Findings in text](docs/findings.md)**

![Busy and free roads at the evening peak and late at night](docs/figures/nb_map_speed_peak_night.png)

## Key findings

The data covers Wednesday 21 October 2026, from 6:23 pm to 12:23 am.

| Question | Answer |
| --- | --- |
| How fast are buses? | Median 8.6 km/h from 6 to 7 pm, rising to 25 km/h after 11 pm |
| Where are roads busy? | At the peak, 45% of bus roads run below 15 km/h, against 14% late at night |
| Which stretch is slowest? | ISBT Anand Vihar to Maharaj Pur Check Post, on the Uttar Pradesh border, at 2.2 km/h |
| Do buses bunch? | One gap in eight between buses of the same route is under 2 minutes |
| Can arrivals be predicted? | LightGBM beats the historical median by 14% on familiar routes and 24% on unseen routes |
| What changed since 2023? | The 2023 timetable assumes a flat 15 km/h, and matched routes ran 23% more evening trips |

## Repository layout

| Path | Contents |
| --- | --- |
| [`docs/index.html`](docs/index.html) | The visual report, published with GitHub Pages |
| [`notebooks/delhi_bus_analysis.ipynb`](notebooks/delhi_bus_analysis.ipynb) | The full analysis with every chart |
| [`docs/findings.md`](docs/findings.md) | Findings and limitations in text |
| [`docs/data-audit.md`](docs/data-audit.md) | Audit of the 2023 timetable |
| [`docs/realtime-audit.md`](docs/realtime-audit.md) | Audit of the live feed |
| [`scripts/`](scripts/) | The data pipeline and chart code |
| [`data/README.md`](data/README.md) | Where the data comes from and how to get it |

## Pipeline

| Step | Script | Output |
| --- | --- | --- |
| 1. Collect live positions | `collect_realtime.py` | `data/raw/realtime/positions/` |
| 2. Clean trajectories and compute speeds | `build_trajectories.py` | `data/processed/trajectories.parquet` |
| 3. Detect stop passages | `match_stops.py` | `data/processed/stop_events.parquet` |
| 4. Rebuild live routes | `build_routes.py` | `data/processed/routes.parquet` |
| 5. Summarise speeds by area and hour | `analyse_speeds.py` | `docs/realtime_summary.json` |
| 6. Measure travel times and bunching | `analyse_routes.py` | `docs/routes_summary.json` |
| 7. Predict arrival times | `model_eta.py` | `docs/model_summary.json` |
| 8. Compare with the 2023 timetable | `compare_2023.py` | `docs/comparison_summary.json` |
| 9. Draw the charts and maps | `charts.py`, called by the notebook | `docs/figures/nb_*.png` |

## Run

```
pip install -r requirements.txt
python scripts/collect_realtime.py --hours 6
python scripts/build_trajectories.py
python scripts/match_stops.py
python scripts/build_routes.py
python scripts/analyse_speeds.py
python scripts/analyse_routes.py
python scripts/model_eta.py
python scripts/compare_2023.py
```

Then run the notebook from top to bottom.

- **API key:** The collector needs a personal key from [Delhi Open Transit Data](https://otd.delhi.gov.in/data/realtime/), set as `OTD_API_KEY` or stored in a local `.env` file.
- **Stop locations:** These come from the archived 2023 timetable. See [data/README.md](data/README.md) for how to get it.
- **Basemaps:** Maps use Esri basemap tiles, which are downloaded once and cached in `data/cache/tiles/`.
- **Older charts:** The analysis scripts also save simpler charts when run on their own. The report and notebook use the `nb_*` charts.

## Data and credits

- **Bus data:** Department of Transport, Government of NCT of Delhi, and IIIT-Delhi, through [Delhi Open Transit Data](https://otd.delhi.gov.in/), used under the portal's [terms](https://otd.delhi.gov.in/static/assets/terms-and-conditions.pdf). Raw data is not included in this repository.
- **2023 timetable:** Archived by Transitland and Mobility Database.
- **Basemaps:** Esri, HERE, Garmin and OpenStreetMap contributors.
