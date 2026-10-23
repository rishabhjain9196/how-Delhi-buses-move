# How Delhi Buses Move in 2026

Six hours of live GPS from more than 6,000 Delhi city buses, turned into maps of busy and free roads, bunching patterns and an arrival-time model.

**[Read the visual report](https://rishabhjain9196.github.io/how-Delhi-buses-move/)** &nbsp;|&nbsp; **[Open the notebook](notebooks/delhi_bus_analysis.ipynb)** &nbsp;|&nbsp; **[Findings in text](docs/findings.md)**

![Busy and free roads at the evening peak and late at night](docs/figures/nb_map_speed_peak_night.png)

## Key findings

The collection runs from 18:23 IST on Wednesday 21 October 2026 to 00:23 IST on 22 October. It covers one evening, not the whole year.

| Question | Answer |
| --- | --- |
| How fast are buses? | Median 8.6 km/h from 6 to 7 pm, rising to 25 km/h after 11 pm |
| Where are roads busy? | At the peak, 45% of qualifying road-grid cells are below 15 km/h, against 14% late at night |
| Which stretch is slowest? | ISBT Anand Vihar to Maharaj Pur Check Post, on the Uttar Pradesh border, at 2.2 km/h |
| Do buses bunch? | One gap in eight between buses of the same route is under 2 minutes |
| Can arrivals be predicted? | LightGBM beats the historical median by 14% on familiar routes and 24% on unseen routes |
| How does the 2023 archive compare? | The timetable assumes a flat 15 km/h. The 290-route frequency comparison contains 23% more observed evening trips, but it compares different snapshots. |

## Interactive report

- The [published report](https://rishabhjain9196.github.io/how-Delhi-buses-move/) contains nine interactive charts, including peak and late-night road maps, headway comparisons and arrival-model tests.
- It explains the dataset, processing steps, libraries, evaluation design, operational implications and limitations. Every chart includes a data table and CSV download.
- Open `docs/index.html` locally to read it without a collector or backend. Plotly.js 4.1.1 is bundled under the [MIT licence](docs/plotly-LICENSE.txt), and the interactive map makes no external tile requests.
- After running the analysis pipeline, run `python scripts/export_report_data.py`. It reads retained trajectories, stop events, routes, polling counts and saved summaries. The optional `--steps` argument accepts a compatible usable-step Parquet file.
- The exporter publishes aggregate grids and route statistics, not vehicle identifiers or individual positions.

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
- **Basemaps:** Notebook maps use Esri tiles, downloaded once and cached in `data/cache/tiles/`. The interactive road map uses the observed GPS grid instead.
- **Saved charts:** The notebook uses the `nb_*` figures. The interactive report uses exported aggregates and includes a supporting saved time-space diagram.

## Data and credits

- **Bus data:** Department of Transport, Government of NCT of Delhi, and IIIT-Delhi, through [Delhi Open Transit Data](https://otd.delhi.gov.in/), used under the portal's [terms](https://otd.delhi.gov.in/static/assets/terms-and-conditions.pdf). Raw data is not included in this repository.
- **2023 timetable:** Archived by Transitland and Mobility Database.
- **Basemaps:** Esri, HERE, Garmin and OpenStreetMap contributors.
