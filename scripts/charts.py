"""Charts and maps for the analysis notebook.

Maps are drawn in Web Mercator on Esri basemap tiles. Tiles are cached in data/cache/tiles.
Road maps are rasters built from the bus GPS points themselves, so they follow real roads
without needing a separate road network.
"""

import functools
import warnings
import zipfile
from pathlib import Path

import contextily as cx
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xyzservices
import xyzservices.providers as xp
from matplotlib.colors import LogNorm, Normalize

ROOT = Path(__file__).resolve().parent.parent
FIGURES = ROOT / "docs" / "figures"
TILE_CACHE = ROOT / "data" / "cache" / "tiles"
FEED = ROOT / "data" / "raw" / "static_bus_archive" / "delhi_bus_gtfs_mdb-1262.zip"

EARTH_RADIUS_M = 6_378_137
DELHI = (76.83, 77.40, 28.40, 28.89)        # lon min, lon max, lat min, lat max
CENTRAL = (77.08, 77.33, 28.53, 28.70)

LIGHT_TILES = xp.Esri.WorldGrayCanvas
DARK_TILES = xyzservices.TileProvider(
    name="Esri.WorldDarkGrayBase",
    url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
    attribution="Esri, HERE, Garmin, OpenStreetMap contributors", max_zoom=16)
CREDIT = "Basemap: Esri, HERE, Garmin, OpenStreetMap contributors.  Bus data: Delhi Open Transit Data."

RED, ORANGE, YELLOW, GREEN, BLUE = "#d73027", "#f46d43", "#fdae61", "#1a9850", "#2563eb"
GREY, DARK_GREY, INK = "#9ca3af", "#4b5563", "#111827"
SPEED_CMAP = plt.get_cmap("RdYlGn")
SPEED_MAX = 30

# Map labels, located at the median position of the matching 2023 stops.
LANDMARKS = {
    "Connaught Place": r"^Regal$", "Kashmere Gate": r"ISBT Kashmere Gate", "Anand Vihar": r"Anand Vihar ISBT",
    "IGI Airport": r"IGI Airport Terminal 2|IGI Terminal 3", "Dwarka": r"Dwarka Sec 21", "Rohini": r"Rohini Sec 5",
    "Nehru Place": r"^Nehru Place", "Najafgarh": r"^Najafgarh Terminal$", "Narela": r"Narela Terminal",
    "Badarpur": r"^Badarpur Border$", "Karol Bagh": r"Karol Bagh", "Punjabi Bagh": r"^Punjabi Bagh Terminal",
    "Shahdara": r"Shahdara Terminal", "Mehrauli": r"^Mehrauli Terminal$", "ITO": r"^ITO", "AIIMS": r"^AIIMS",
    "Saket": r"Saket",
}
CITY_LABELS = ["Connaught Place", "Kashmere Gate", "Anand Vihar", "IGI Airport", "Dwarka", "Rohini", "Nehru Place",
               "Najafgarh", "Narela", "Badarpur", "Punjabi Bagh", "Shahdara", "Saket"]
CENTRAL_LABELS = ["Connaught Place", "Kashmere Gate", "ITO", "Karol Bagh", "AIIMS", "Nehru Place", "Punjabi Bagh"]
LEFT_LABELS = {"Connaught Place"}       # drawn to the left of the point to avoid crowding


# ---------- Setup and helpers ----------

def setup():
    warnings.filterwarnings("ignore")
    TILE_CACHE.mkdir(parents=True, exist_ok=True)
    cx.set_cache_dir(str(TILE_CACHE))
    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 150, "savefig.bbox": "tight",
        "font.family": "sans-serif", "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
        "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
        "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#d1d5db",
        "axes.labelcolor": DARK_GREY, "xtick.color": DARK_GREY, "ytick.color": DARK_GREY,
        "axes.grid": True, "grid.color": "#e5e7eb", "grid.linewidth": 0.8, "axes.axisbelow": True,
        "legend.frameon": False,
    })


def header(fig, title, subtitle=None, y=1.0):
    """Insight-led title and a grey subtitle, aligned to the left of the figure."""
    fig.text(0.01, y + 0.06, title, fontsize=15, fontweight="bold", color=INK, ha="left", va="bottom")
    if subtitle:
        fig.text(0.01, y + 0.015, subtitle, fontsize=10, color=DARK_GREY, ha="left", va="bottom")


def save(fig, name):
    fig.savefig(FIGURES / name)


def to_mercator(lon, lat):
    lon, lat = np.asarray(lon, dtype=float), np.asarray(lat, dtype=float)
    x = EARTH_RADIUS_M * np.radians(lon)
    y = EARTH_RADIUS_M * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
    return x, y


def base_map(ax, bounds=DELHI, dark=True, zoom=12):
    x0, y0 = to_mercator(bounds[0], bounds[2])
    x1, y1 = to_mercator(bounds[1], bounds[3])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    cx.add_basemap(ax, source=DARK_TILES if dark else LIGHT_TILES, zoom=zoom, attribution=False, reset_extent=True)
    ax.set_axis_off()
    ax.set_aspect("equal")


@functools.lru_cache(maxsize=1)
def landmark_points():
    stops = pd.read_csv(zipfile.ZipFile(FEED).open("stops.txt"))
    rows = []
    for name, pattern in LANDMARKS.items():
        match = stops[stops.stop_name.str.contains(pattern, case=False, regex=True)]
        rows.append({"name": name, "lat": match.stop_lat.median(), "lon": match.stop_lon.median()})
    return pd.DataFrame(rows).set_index("name")


def label(ax, names, dark=True, size=8.5):
    points = landmark_points().loc[names]
    x, y = to_mercator(points.lon, points.lat)
    colour, halo = ("white", "black") if dark else (INK, "white")
    ax.scatter(x, y, s=10, color=colour, edgecolor=halo, linewidth=0.6, zorder=5)
    for name, xi, yi in zip(points.index, x, y):
        left = name in LEFT_LABELS
        ax.text(xi, yi, f"{name} " if left else f" {name}", fontsize=size, color=colour, va="center", zorder=6,
                ha="right" if left else "left", path_effects=[pe.withStroke(linewidth=2.5, foreground=halo)])


def credit(fig, y=-0.01):
    fig.text(0.01, y, CREDIT, fontsize=7, color=GREY, ha="left", va="top")


def map_figure(width=9, height=9.6):
    fig = plt.figure(figsize=(width, height))
    ax = fig.add_axes([0.01, 0.04, 0.98, 0.84])
    return fig, ax


def pixel_keys(df, bounds, pixel_m):
    x, y = to_mercator(df.lon.values, df.lat.values)
    x0, y0 = to_mercator(bounds[0], bounds[2])
    x1, y1 = to_mercator(bounds[1], bounds[3])
    nx, ny = int((x1 - x0) // pixel_m) + 1, int((y1 - y0) // pixel_m) + 1
    ix, iy = ((x - x0) // pixel_m).astype(int), ((y - y0) // pixel_m).astype(int)
    inside = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny)
    return iy * nx + ix, inside, (nx, ny), (x0, x0 + nx * pixel_m, y0, y0 + ny * pixel_m)


def speed_grid(steps, bounds, pixel_m, min_count=3, smooth=3):
    """Space-mean speed per pixel: total distance over total time, averaged with neighbouring pixels.

    Averaging distance and time separately keeps a short stop at one pixel from colouring the road red.
    """
    from scipy.ndimage import uniform_filter
    keys, inside, (nx, ny), extent = pixel_keys(steps, bounds, pixel_m)
    frame = pd.DataFrame({"key": keys[inside], "dist": steps.dist_m.values[inside], "dt": steps.dt_s.values[inside]})
    sums = frame.groupby("key").agg(dist=("dist", "sum"), dt=("dt", "sum"), n=("dt", "size"))
    grids = {}
    for column in ("dist", "dt", "n"):
        grid = np.zeros(nx * ny)
        grid[sums.index] = sums[column].values
        grids[column] = grid.reshape(ny, nx)
    dist, dt = (uniform_filter(grids[c], size=smooth) for c in ("dist", "dt")) if smooth > 1 else (grids["dist"], grids["dt"])
    with np.errstate(divide="ignore", invalid="ignore"):
        speed = dist / dt * 3.6
    return np.where(grids["n"] >= min_count, speed, np.nan), extent


def share_below(grid, threshold):
    valid = grid[np.isfinite(grid)]
    return (valid < threshold).mean()


def rasterise(df, bounds, pixel_m, value=None, stat="median", min_count=3):
    """Aggregate GPS points onto a square Web Mercator grid. Returns the grid and its extent."""
    keys, inside, (nx, ny), extent = pixel_keys(df, bounds, pixel_m)
    frame = pd.DataFrame({"key": keys[inside]})
    if value == "buses":
        frame["vehicle_id"] = df.vehicle_id.values[inside]
        groups = frame.groupby("key")
        result, count = groups.vehicle_id.nunique(), groups.size()
    elif value:
        frame[value] = df[value].values[inside]
        groups = frame.groupby("key")
        result, count = groups[value].agg(stat), groups.size()
    else:
        result = count = frame.groupby("key").size()
    grid = np.full(nx * ny, np.nan)
    keep = count[count >= min_count].index
    grid[keep] = result.loc[keep].values
    return grid.reshape(ny, nx), extent


def colourbar(fig, ax, mappable, text, position=(0.6, 0.05, 0.36, 0.022), dark=True):
    cax = ax.inset_axes(position)
    bar = fig.colorbar(mappable, cax=cax, orientation="horizontal")
    colour = "white" if dark else INK
    bar.set_label(text, color=colour, fontsize=8.5)
    bar.ax.xaxis.set_label_position("top")
    bar.ax.tick_params(colors=colour, labelsize=7.5)
    bar.outline.set_visible(False)
    return bar


# ---------- Overview ----------

def at_a_glance(numbers):
    fig, axes = plt.subplots(1, len(numbers), figsize=(13, 1.9))
    for ax, (value, text) in zip(axes, numbers):
        ax.set_axis_off()
        ax.add_patch(plt.Rectangle((0, 0), 1, 1, transform=ax.transAxes, color="#f3f4f6", zorder=0))
        ax.text(0.08, 0.58, value, fontsize=21, fontweight="bold", color=INK, transform=ax.transAxes)
        ax.text(0.08, 0.22, text, fontsize=9.5, color=DARK_GREY, transform=ax.transAxes)
    fig.subplots_adjust(wspace=0.08)
    save(fig, "nb_at_a_glance.png")


def traffic_map(steps, name="nb_map_bus_traffic.png"):
    grid, extent = rasterise(steps, DELHI, 90, value="buses", min_count=2)
    fig, ax = map_figure()
    base_map(ax, DELHI, dark=True)
    image = ax.imshow(grid, origin="lower", extent=extent, cmap="inferno", norm=LogNorm(2, np.nanmax(grid)),
                      interpolation="nearest", zorder=2)
    label(ax, CITY_LABELS)
    colourbar(fig, ax, image, "Different buses passing each 90 m of road")
    busy = np.nanpercentile(grid, 99)
    header(fig, f"Delhi's bus network, traced by {steps.vehicle_id.nunique():,} moving buses in one evening",
           f"Each pixel is 90 m of road. The brightest 1% carried {busy:.0f} or more different buses from 6:23 pm to 12:23 am.",
           y=0.885)
    credit(fig, y=0.035)
    save(fig, name)


def fleet_on_road(log):
    log = log.assign(time=pd.to_datetime(log.polled_at, unit="s", utc=True).dt.tz_convert("Asia/Kolkata"))
    live = log[log.vehicles > 0]
    empty = log[log.vehicles == 0]
    fig, ax = plt.subplots(figsize=(11, 3.4))
    ax.fill_between(live.time, live.vehicles, color=BLUE, alpha=0.18, linewidth=0)
    ax.plot(live.time, live.vehicles.rolling(30, min_periods=1).median(), color=BLUE, linewidth=2)
    ax.scatter(empty.time, np.zeros(len(empty)), marker="|", s=60, color=RED, label=f"Empty response ({len(empty)} polls)")
    ax.set_ylabel("Buses in the feed")
    ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%H:%M", tz=live.time.dt.tz))
    ax.legend(loc="lower left")
    ax.set_ylim(0, live.vehicles.max() * 1.1)
    peak = int(live.vehicles.max())
    header(fig, f"Up to {peak:,} buses reported at once, and the fleet thins steadily after 8 pm",
           f"Feed polled every 10 seconds, {len(log):,} polls in total. The line is a 5-minute rolling median.", y=0.92)
    save(fig, "nb_fleet_on_road.png")


def timetable_speeds(segments):
    fig, ax = plt.subplots(figsize=(11, 3.4))
    ax.hist(segments.speed_kmh.clip(5, 30), bins=np.arange(5, 30.25, 0.25), color=GREY)
    ax.axvline(15, color=RED, linewidth=1.5)
    share = segments.speed_kmh.between(14.5, 15.5).mean()
    ax.annotate(f"{share:.1%} of scheduled hops\nimply 14.5 to 15.5 km/h", xy=(15.1, 1e6), xytext=(19, 2e5), color=RED, fontsize=9,
                arrowprops=dict(arrowstyle="->", color=RED))
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel("Speed implied by the timetable between consecutive stops (km/h)")
    ax.set_ylabel("Stop-to-stop hops (log scale)")
    header(fig, "The published timetable assumes every bus moves at a constant 15 km/h",
           "2023 timetable: straight-line distance between stops divided by the scheduled time.", y=0.92)
    save(fig, "nb_timetable_speeds.png")


# ---------- Speed ----------

BANDS = [(-1, 5, "Crawling (under 5 km/h)", RED), (5, 15, "Slow (5 to 15 km/h)", YELLOW),
         (15, 30, "Moderate (15 to 30 km/h)", "#a6d96a"), (30, 100, "Free-flowing (over 30 km/h)", GREEN)]


def speed_timeline(steps):
    slot = steps.time.dt.floor("15min")
    complete = slot < steps.time.max().floor("15min")      # drop the final, partial 15 minutes
    steps, slot = steps[complete], slot[complete]
    quantiles = steps.groupby(slot).speed_kmh.quantile([0.25, 0.5, 0.75]).unstack()
    bands = pd.cut(steps.speed_kmh, [b[0] for b in BANDS] + [BANDS[-1][1]], labels=[b[2] for b in BANDS])
    shares = pd.crosstab(slot, bands, normalize="index")
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, gridspec_kw={"height_ratios": [1, 1.1]})
    top.fill_between(quantiles.index, quantiles[0.25], quantiles[0.75], color=BLUE, alpha=0.15, label="Middle 50% of observations")
    top.plot(quantiles.index, quantiles[0.5], color=BLUE, linewidth=2.2, label="Median")
    top.set_ylabel("Speed (km/h)")
    top.legend(loc="upper left")
    top.set_title("Bus speed every 15 minutes")
    bottom.stackplot(shares.index, shares.T.values, colors=[b[3] for b in BANDS], labels=[b[2] for b in BANDS], alpha=0.9)
    bottom.set_ylim(0, 1)
    bottom.yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1))
    bottom.set_ylabel("Share of moving-bus time")
    bottom.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=4)
    bottom.set_title("How bus time splits between speed bands")
    bottom.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%H:%M", tz=shares.index.tz))
    first, last = shares.iloc[0, 0], shares.iloc[-1, 0]
    header(fig, f"Buses spend {first:.0%} of their time crawling at 6:15 pm, falling to {last:.0%} by midnight",
           "Speed from consecutive GPS positions of moving buses. Parked buses are excluded.", y=0.93)
    fig.subplots_adjust(hspace=0.3)
    save(fig, "nb_speed_timeline.png")
    return shares, quantiles


def speed_by_distance(steps, peak_hours=(18, 19), night_hours=(22, 23, 0)):
    centre = landmark_points().loc["Connaught Place"]
    km = np.hypot((steps.lat - centre.lat) * 110.54, (steps.lon - centre.lon) * 111.32 * np.cos(np.radians(centre.lat)))
    ring = (km // 1).clip(upper=29)
    hour = steps.time.dt.hour
    fig, ax = plt.subplots(figsize=(11, 3.8))
    result = {}
    for hours, colour, name in [(peak_hours, RED, "Evening peak, 6 to 8 pm"), (night_hours, GREEN, "Late night, 10 pm to 12:23 am")]:
        q = steps.speed_kmh[hour.isin(hours)].groupby(ring[hour.isin(hours)]).quantile([0.25, 0.5, 0.75]).unstack()
        ax.fill_between(q.index + 0.5, q[0.25], q[0.75], color=colour, alpha=0.12)
        ax.plot(q.index + 0.5, q[0.5], color=colour, linewidth=2.2, label=name)
        result[name] = q[0.5]
    ax.set_xlabel("Distance from Connaught Place (km)")
    ax.set_ylabel("Median speed (km/h)")
    ax.legend(loc="upper left")
    peak = result["Evening peak, 6 to 8 pm"]
    inner, outer = peak.loc[1:18].median(), peak.loc[19:].median()
    header(fig, f"At the peak, buses crawl at about {inner:.0f} km/h almost everywhere within 19 km of the centre",
           f"Beyond 19 km, peak speeds roughly double to about {outer:.0f} km/h. Shaded bands show the middle 50% of observations.",
           y=0.92)
    save(fig, "nb_speed_by_distance.png")
    return pd.DataFrame(result)


def speed_maps(steps):
    hour = steps.time.dt.hour
    periods = [("Evening peak, 6:23 to 8 pm", hour.isin([18, 19])), ("Late night, 10 pm to 12:23 am", hour.isin([22, 23, 0]))]
    fig = plt.figure(figsize=(15, 8.4))
    norm = Normalize(0, SPEED_MAX)
    shares = {}
    for i, (name, mask) in enumerate(periods):
        ax = fig.add_axes([0.005 + i * 0.5, 0.04, 0.49, 0.78])
        grid, extent = speed_grid(steps[mask], DELHI, 110)
        base_map(ax, DELHI, dark=True)
        image = ax.imshow(grid, origin="lower", extent=extent, cmap=SPEED_CMAP, norm=norm, interpolation="nearest", zorder=2)
        label(ax, ["Connaught Place", "Anand Vihar", "IGI Airport", "Rohini", "Najafgarh", "Badarpur"], size=8)
        shares[name] = share_below(grid, 15)
        ax.set_title(f"{name}:  {shares[name]:.0%} of roads below 15 km/h", color=INK, loc="left", fontsize=12)
    colourbar(fig, ax, image, "Bus speed (km/h)")
    header(fig, "The same roads that crawl at the evening peak flow freely by late night",
           "Each pixel is 110 m of road, coloured by bus speed (total distance over total time, smoothed with neighbouring pixels).",
           y=0.875)
    credit(fig, y=0.035)
    save(fig, "nb_map_speed_peak_night.png")
    return shares


def central_map(steps):
    peak = steps[steps.time.dt.hour.isin([18, 19])]
    grid, extent = speed_grid(peak, CENTRAL, 45)
    fig, ax = map_figure(11, 8.6)
    base_map(ax, CENTRAL, dark=True, zoom=13)
    image = ax.imshow(grid, origin="lower", extent=extent, cmap=SPEED_CMAP, norm=Normalize(0, SPEED_MAX),
                      interpolation="nearest", zorder=2)
    label(ax, CENTRAL_LABELS, size=9.5)
    colourbar(fig, ax, image, "Bus speed (km/h)")
    share = share_below(grid, 15)
    header(fig, f"Central Delhi at the evening peak: {share:.0%} of bus roads run below 15 km/h",
           "Each pixel is 45 m of road, 6:23 to 8 pm. The wide avenues of New Delhi, south of Connaught Place, stay mostly green.",
           y=0.885)
    credit(fig, y=0.035)
    save(fig, "nb_map_central_peak.png")
    return share


def peak_cost_map(steps):
    hour = steps.time.dt.hour
    peak, _ = speed_grid(steps[hour.isin([18, 19])], DELHI, 110, min_count=5)
    night, extent = speed_grid(steps[hour.isin([22, 23, 0])], DELHI, 110, min_count=5)
    with np.errstate(divide="ignore", invalid="ignore"):
        extra = 60 / np.clip(peak, 1, None) - 60 / np.clip(night, 1, None)
    extra = np.where(np.isfinite(extra), np.clip(extra, 0, 8), np.nan)
    fig, ax = map_figure()
    base_map(ax, DELHI, dark=False)
    image = ax.imshow(extra, origin="lower", extent=extent, cmap="YlOrRd", norm=Normalize(0, 8),
                      interpolation="nearest", zorder=2)
    label(ax, CITY_LABELS, dark=False)
    colourbar(fig, ax, image, "Extra minutes per km at the peak (capped at 8)", dark=False)
    header(fig, f"The evening peak adds a median {np.nanmedian(extra):.1f} minutes to every kilometre a bus travels",
           "Extra time per km at 6:23 to 8 pm compared with 10 pm to 12:23 am, on roads with buses in both periods.", y=0.885)
    credit(fig, y=0.035)
    save(fig, "nb_map_peak_cost.png")
    return extra


# ---------- Slowest stretches ----------

def slowest_stretches(ranked, n=10):
    # Keep the slowest segment per pair of place names, so one corridor does not take several places.
    ranked = ranked.sort_values("median_kmh")
    top = ranked.drop_duplicates("to_stop").head(n).reset_index(drop=True)
    fig = plt.figure(figsize=(15, 7.4))
    ax_map = fig.add_axes([0, 0.02, 0.43, 0.84])
    ax_bar = fig.add_axes([0.62, 0.08, 0.37, 0.78])
    base_map(ax_map, DELHI, dark=False)
    x0, y0 = to_mercator(ranked.lon, ranked.lat)
    x1, y1 = to_mercator(ranked.next_lon, ranked.next_lat)
    colours = SPEED_CMAP(Normalize(0, SPEED_MAX)(ranked.median_kmh.clip(upper=SPEED_MAX)))
    for a, b, c, d, colour in zip(x0, x1, y0, y1, colours):
        ax_map.plot([a, b], [c, d], color=colour, linewidth=1, alpha=0.6, zorder=2)
    mx, my = to_mercator((top.lon + top.next_lon) / 2, (top.lat + top.next_lat) / 2)
    placed = []
    for i, (xi, yi) in enumerate(zip(mx, my), 1):
        # Nudge markers that would sit on top of an earlier one.
        while any(np.hypot(xi - px, yi - py) < 1300 for px, py in placed):
            yi += 1300
        placed.append((xi, yi))
        ax_map.scatter(xi, yi, s=190, color=INK, edgecolor="white", linewidth=1, zorder=4)
        ax_map.text(xi, yi, str(i), color="white", fontsize=8, fontweight="bold", ha="center", va="center", zorder=5)
    short = lambda s: s if len(s) <= 26 else s[:24].rstrip() + "..."
    names = [f"{i}. {short(a)} to {short(b)}" for i, (a, b) in enumerate(zip(top.from_stop, top.to_stop), 1)]
    ax_bar.hlines(range(n), 0, top.median_kmh, color=RED, linewidth=2)
    ax_bar.scatter(top.median_kmh, range(n), color=RED, s=60, zorder=3)
    for i, row in top.iterrows():
        ax_bar.text(row.median_kmh + 0.25, i, f"{row.median_kmh:.1f} km/h  ({row.median_s / 60:.1f} min for {row.distance_m:.0f} m)",
                    va="center", fontsize=8.5, color=DARK_GREY)
    ax_bar.set_yticks(range(n), names, fontsize=8.5)
    ax_bar.invert_yaxis()
    ax_bar.set_xlim(0, 10)
    ax_bar.set_xlabel("Median speed between the two stops (km/h)")
    ax_bar.grid(axis="y", visible=False)
    header(fig, "The slowest stretches sit at the Uttar Pradesh border, the airport road and western depots",
           f"Ranked from {len(ranked):,} stop-to-stop segments of at least 250 m with 10 or more buses. Map lines are coloured by median speed.",
           y=0.88)
    credit(fig, y=0.0)
    save(fig, "nb_slowest_stretches.png")


# ---------- Bunching ----------

def time_space(passages, stop_names, title_name, start, end, bunched_s=120, max_hop_s=480, max_seq_jump=3):
    """Each line is one bus trip moving along the route. Red dots mark arrivals within 2 minutes of the previous bus."""
    p = passages[(passages.arrival_ts >= start) & (passages.arrival_ts <= end)].copy()
    p["time"] = pd.to_datetime(p.arrival_ts, unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    p = p.sort_values(["seq", "arrival_ts"])
    p["gap_s"] = p.groupby("seq").arrival_ts.diff()
    bunched = p[p.gap_s < bunched_s]
    fig, ax = plt.subplots(figsize=(13, 6.5))
    for _, trip in p.sort_values("arrival_ts").groupby("trip_key"):
        # Break the line at halts and at long jumps along the route, where stops in between were missed.
        new_piece = (trip.arrival_ts.diff() > max_hop_s) | (trip.seq.diff() > max_seq_jump)
        for _, part in trip.groupby(new_piece.cumsum()):
            if len(part) >= 2:
                ax.plot(part.time, part.seq, color=BLUE, linewidth=1.3, alpha=0.75)
    ax.scatter(bunched.time, bunched.seq, color=RED, s=22, zorder=3, label="Arrived within 2 minutes of the previous bus")
    ax.set_ylim(p.seq.min() - 0.5, p.seq.max() + 0.5)
    ax.set_xlim(pd.Timestamp(start, unit="s", tz="UTC"), pd.Timestamp(end, unit="s", tz="UTC"))
    ticks = sorted(p.seq.unique())[::max(1, p.seq.nunique() // 10)]
    ax.set_yticks(ticks, [stop_names.get(t, "")[:30] for t in ticks], fontsize=8)
    ax.set_ylabel("Stops along the route (direction of travel is upwards)")
    ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter("%H:%M", tz=p.time.dt.tz))
    ax.legend(loc="upper left", bbox_to_anchor=(0, -0.08))
    share = len(bunched) / len(p)
    header(fig, f"Route {title_name}: {share:.0%} of stop arrivals came within 2 minutes of the bus ahead",
           "Each blue line is one bus moving along the route over time. Lines that run together are buses travelling in a bunch.",
           y=0.92)
    save(fig, "nb_bunching_time_space.png")
    return share


def headway_zones(gaps, bunched_s=120):
    minutes = gaps.gap_s / 60
    zones = [(0, bunched_s / 60, "Bunched, under 2 min", RED), (bunched_s / 60, 15, "2 to 15 min", GREEN),
             (15, 30, "15 to 30 min", YELLOW), (30, 61, "Over 30 min", ORANGE)]
    fig, ax = plt.subplots(figsize=(11, 3.8))
    bins = np.arange(0, 61, 1)
    counts, edges = np.histogram(minutes.clip(upper=60), bins=bins)
    for lo, hi, name, colour in zones:
        mask = (edges[:-1] >= lo) & (edges[:-1] < hi)
        share = ((minutes >= lo) & (minutes < hi)).mean() if hi < 61 else (minutes >= lo).mean()
        ax.bar(edges[:-1][mask], counts[mask], width=1, align="edge", color=colour, label=f"{name}: {share:.0%}")
    ax.set_xlabel("Minutes between consecutive buses of the same route at the same stop (60 means 60 or more)")
    ax.set_ylabel("Gaps")
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.FuncFormatter(lambda v, _: f"{v / 1000:.0f}k"))
    ax.legend(loc="upper center")
    header(fig, f"One gap in {round(1 / (minutes < bunched_s / 60).mean())} is a bus arriving right behind another",
           f"{len(gaps):,} gaps between buses of the same route at the same stop.", y=0.92)
    save(fig, "nb_headway_zones.png")


def route_reliability(by_route):
    df = by_route.assign(median_gap_min=by_route.median_gap_s / 60)
    fig, ax = plt.subplots(figsize=(11, 4.6))
    colours = np.where(df.cv >= 1, RED, np.where(df.cv >= 0.5, YELLOW, GREEN))
    ax.scatter(df.median_gap_min, df.cv, s=np.clip(df.buses * 2, 10, 120), c=colours, alpha=0.6, edgecolor="white", linewidth=0.5)
    ax.axhline(1, color=DARK_GREY, linestyle="--", linewidth=1)
    ax.axhline(0.5, color=GREY, linestyle=":", linewidth=1)
    ax.set_xscale("log")
    ax.set_xticks([2, 5, 10, 20, 40], ["2", "5", "10", "20", "40"])
    ax.minorticks_off()
    right = ax.get_xlim()[1]
    ax.text(right, 1.03, "Random arrivals ", color=DARK_GREY, fontsize=8.5, ha="right")
    ax.text(right, 0.53, "Fairly regular ", color=GREY, fontsize=8.5, ha="right")
    ax.set_xlabel("Typical gap between buses on the route (minutes, log scale)")
    ax.set_ylabel("Irregularity of gaps\n(coefficient of variation)")
    ax.set_ylim(0, min(3, df.cv.max() * 1.05))
    irregular = (df.cv >= 1).mean()
    header(fig, f"{irregular:.0%} of routes have gaps as irregular as random arrivals, or worse",
           f"{len(df)} routes with 6 or more buses at a stop. Dot size shows the number of buses.", y=0.92)
    save(fig, "nb_route_reliability.png")
    return irregular


# ---------- Arrival-time model ----------

FEATURE_NAMES = {"distance_m": "Distance to the target stop", "stop_id": "Starting stop", "horizon": "Number of stops ahead",
                 "route_id": "Route", "live_speed": "Live speed of buses ahead", "hour": "Time of evening",
                 "own_speed": "Bus's own recent speed", "live_age_s": "Age of the live speed"}
METHOD_COLOURS = {"Historical median": GREY, "Own recent speed": YELLOW, "LightGBM": BLUE}


def eta_results(table, main_results):
    fig, (left, right) = plt.subplots(1, 2, figsize=(14, 4.6), gridspec_kw={"width_ratios": [1, 1.1]})
    tests = list(table.index)
    width = 0.26
    for i, method in enumerate(METHOD_COLOURS):
        values = table[f"{method} MAE (s)"]
        bars = left.bar(np.arange(len(tests)) + (i - 1) * width, values, width, color=METHOD_COLOURS[method], label=method)
        left.bar_label(bars, fmt="%.0f", fontsize=8, padding=2)
    left.set_xticks(range(len(tests)), tests)
    left.set_ylabel("Mean absolute error (s)")
    left.set_ylim(0, table.values.max() * 1.25)
    left.legend(loc="upper left", ncol=3, fontsize=8.5)
    left.set_title("Error in each test (lower is better)")
    for method, result in main_results.items():
        h = result["mae_by_horizon_s"]
        right.plot([int(k) for k in h], list(h.values()), marker="o", color=METHOD_COLOURS[method], linewidth=2, label=method)
    right.set_xticks(range(1, 11))
    right.set_xlabel("Stops ahead")
    right.set_ylabel("Mean absolute error (s)")
    right.set_title("Error by distance ahead, later-evening test")
    gain = 1 - table.loc["Same hours", "LightGBM MAE (s)"] / table.loc["Same hours", "Historical median MAE (s)"]
    header(fig, f"LightGBM predicts arrivals {gain:.0%} more accurately than history when both see the same hours",
           "Three tests: later evening (train early, test late), same hours (alternating 30-minute blocks) and unseen routes.",
           y=0.93)
    save(fig, "nb_eta_results.png")


def eta_features(importance):
    shares = importance.rename(FEATURE_NAMES).sort_values()
    fig, ax = plt.subplots(figsize=(11, 3.6))
    colours = [BLUE if v >= 0.1 else GREY for v in shares]
    bars = ax.barh(shares.index, shares.values, color=colours)
    ax.bar_label(bars, labels=[f"{v:.0%}" if v >= 0.005 else "<1%" for v in shares.values], fontsize=8.5, padding=3)
    ax.xaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1, decimals=0))
    ax.set_xlabel("Share of the model's total gain")
    ax.grid(axis="y", visible=False)
    header(fig, "Where the bus is and how far it must go matter most; its own recent speed barely matters",
           "LightGBM feature importance (gain) in the later-evening test.", y=0.92)
    save(fig, "nb_eta_features.png")


# ---------- Comparison with 2023 ----------

def timetable_ratio(hourly):
    labels = [f"{h:02d}:00" for h in hourly.index]
    fig, ax = plt.subplots(figsize=(11, 3.8))
    colours = [RED if s >= 0.4 else YELLOW if s >= 0.2 else GREEN for s in hourly.share_slower]
    bars = ax.bar(labels, hourly.median_ratio * 100, color=colours, width=0.65)
    ax.bar_label(bars, labels=[f"{s:.0%} slower\nthan plan" for s in hourly.share_slower], fontsize=8, padding=3)
    ax.axhline(100, color=INK, linewidth=1.2)
    ax.text(len(labels) - 0.5, 104, "Timetable time", ha="right", fontsize=8.5, color=INK)
    ax.set_ylim(0, 135)
    ax.set_ylabel("Observed time as a % of\nthe timetable's time")
    ax.set_xlabel("Hour starting (IST)")
    header(fig, "The 2023 timetable is roughly right at 6 pm but twice too slow after midnight",
           "Median observed stop-to-stop time divided by the 2023 timetable's time for the same stop pair.", y=0.92)
    save(fig, "nb_timetable_ratio.png")


def planned_vs_observed(freq):
    df = freq.assign(ratio=freq.observed_trips / freq.planned_trips).sort_values("ratio")
    groups = [("Under half the plan", df.ratio < 0.5, RED), ("Half to double", df.ratio.between(0.5, 2), GREY),
              ("Over double", df.ratio > 2, BLUE)]
    fig, (left, right) = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1, 1.25]})
    totals = [df.planned_trips.sum(), df.observed_trips.sum()]
    bars = left.bar(["Planned in 2023", "Observed in 2026"], totals, color=[GREY, BLUE], width=0.55)
    left.bar_label(bars, labels=[f"{v:,.0f} trips" for v in totals], fontsize=10, padding=3)
    left.set_ylabel("Trips, 7 to 11 pm")
    left.set_ylim(0, max(totals) * 1.2)
    left.set_title(f"All {len(df)} matched routes together")
    counts = [mask.sum() for _, mask, _ in groups]
    bars = right.barh([name for name, _, _ in groups], counts, color=[c for _, _, c in groups])
    right.bar_label(bars, labels=[f"{c} routes ({c / len(df):.0%})" for c in counts], fontsize=9, padding=3)
    right.invert_yaxis()
    right.set_xlim(0, max(counts) * 1.4)
    right.set_xlabel("Routes")
    right.grid(axis="y", visible=False)
    right.set_title("Each route's 2026 trips compared with its 2023 plan")
    fig.subplots_adjust(wspace=0.45)
    change = totals[1] / totals[0] - 1
    header(fig, f"Matched routes ran {change:.0%} more evening trips than the 2023 plan, but individual routes vary widely",
           "Routes whose stops match a 2023 route strongly. Per-route changes also reflect routes being merged, split or renumbered.",
           y=0.92)
    save(fig, "nb_planned_vs_observed.png")
    return change


def network_change_map(clusters, cells, new_area_m=500):
    fig, ax = map_figure()
    base_map(ax, DELHI, dark=False)
    served, unserved = clusters[clusters.buses >= 3], clusters[clusters.buses < 3]
    new = cells[cells.nearest_stop_m > new_area_m]
    for df, colour, size, text in [(served, GREY, 3, f"2023 stops passed by buses ({len(served):,})"),
                                   (unserved, RED, 9, f"2023 stops not passed ({len(unserved):,})")]:
        x, y = to_mercator(df.stop_lon, df.stop_lat)
        ax.scatter(x, y, s=size, color=colour, label=text, zorder=3)
    x, y = to_mercator(new.lon, new.lat)
    ax.scatter(x, y, s=10, marker="s", color=BLUE, label=f"Bus areas over {new_area_m} m from any 2023 stop ({len(new):,})", zorder=3)
    label(ax, CITY_LABELS, dark=False)
    ax.legend(loc="lower left", fontsize=9, facecolor="white", frameon=True)
    share = len(served) / len(clusters)
    header(fig, f"{share:.0%} of 2023 stop locations still saw buses, and new corridors run beyond them",
           "Stops are 2023 stop locations merged into clusters. Blue squares are 450 m areas with bus traffic far from any 2023 stop.",
           y=0.885)
    credit(fig, y=0.035)
    save(fig, "nb_map_network_change.png")


def fleet_mix(series, total):
    labels = {"DL1PD": "DL1PD", "DL51EV": "DL51EV (likely electric)", "DL51GD": "DL51GD", "DL1PE": "DL1PE"}
    values = pd.Series(series)
    fig, ax = plt.subplots(figsize=(7, 4.6))
    colours = [BLUE, GREEN, YELLOW, GREY, DARK_GREY][:len(values)]
    wedges, _ = ax.pie(values, colors=colours, startangle=90, counterclock=False, wedgeprops=dict(width=0.38, edgecolor="white"))
    ax.text(0, 0, f"{total:,}\nbuses", ha="center", va="center", fontsize=14, fontweight="bold", color=INK)
    ax.legend(wedges, [f"{labels.get(k, k)}: {v:,} ({v / total:.0%})" for k, v in values.items()],
              loc="center left", bbox_to_anchor=(1, 0.5))
    header(fig, "Registration series of all buses in the live feed", "The EV series name suggests electric buses; this was not checked against an official list.", y=0.95)
    save(fig, "nb_fleet_mix.png")
