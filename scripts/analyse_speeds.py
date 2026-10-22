"""Summarise bus speeds across Delhi by grid cell and hour.

Speeds include time spent at stops and signals, so they show operating speed, not free-flow speed.

Usage:
    python scripts/analyse_speeds.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
TRAJECTORIES = ROOT / "data" / "processed" / "trajectories.parquet"
FIGURES = ROOT / "docs" / "figures"
SUMMARY = ROOT / "docs" / "realtime_summary.json"

CELL_DEG = 0.004          # about 400 to 450 m
MIN_BUSES_PER_CELL = 3
MIN_STEPS_PER_CELL = 10


def usable_steps(df=None):
    """Moving-bus steps with hour and grid cell. Reads the saved trajectories if none are passed."""
    if df is None:
        df = pd.read_parquet(TRAJECTORIES, columns=["vehicle_id", "lat", "lon", "speed_kmh", "step", "time"])
    df = df.loc[df.step == "ok", ["vehicle_id", "lat", "lon", "speed_kmh", "time"]].copy()
    df["hour"] = df.time.dt.floor("h").dt.strftime("%H:00")
    df["hour_start"] = df.time.dt.floor("h")
    df["cell_x"] = np.floor(df.lon / CELL_DEG).astype(int)
    df["cell_y"] = np.floor(df.lat / CELL_DEG).astype(int)
    return df


def by_hour(df):
    out = df.groupby(["hour_start", "hour"]).agg(median_kmh=("speed_kmh", "median"), mean_kmh=("speed_kmh", "mean"),
                                                 buses=("vehicle_id", "nunique"), steps=("speed_kmh", "size"))
    return out.reset_index(level="hour_start", drop=True).round(1)


def by_cell(df):
    cells = df.groupby(["cell_x", "cell_y"]).agg(median_kmh=("speed_kmh", "median"), steps=("speed_kmh", "size"),
                                                 buses=("vehicle_id", "nunique"))
    cells = cells[(cells.buses >= MIN_BUSES_PER_CELL) & (cells.steps >= MIN_STEPS_PER_CELL)].reset_index()
    cells["lon"] = (cells.cell_x + 0.5) * CELL_DEG
    cells["lat"] = (cells.cell_y + 0.5) * CELL_DEG
    return cells


def plot_cells(cells, title, name):
    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    cells = cells.sort_values("median_kmh", ascending=False)
    points = ax.scatter(cells.lon, cells.lat, c=cells.median_kmh.clip(0, 30), s=7, marker="s", cmap="RdYlGn")
    ax.set_aspect(1 / np.cos(np.radians(28.6)))
    ax.set_xlim(76.84, 77.42)
    ax.set_ylim(28.40, 28.90)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(title)
    fig.colorbar(points, ax=ax, shrink=0.7, label="Median bus speed (km/h, capped at 30)")
    fig.savefig(FIGURES / name, dpi=130, bbox_inches="tight")
    plt.close(fig)


def plot_hours(hours):
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.plot(hours.index, hours.median_kmh, marker="o", color="#2563eb", label="Median speed")
    ax.set_xlabel("Hour starting (IST)")
    ax.set_ylabel("Speed (km/h)")
    ax2 = ax.twinx()
    ax2.bar(hours.index, hours.buses, alpha=0.2, color="#64748b", label="Buses reporting")
    ax2.set_ylabel("Buses reporting")
    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)
    ax.set_title("Bus speed and fleet size by hour")
    fig.savefig(FIGURES / "speed_by_hour.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    df = usable_steps()
    hours = by_hour(df)
    cells = by_cell(df)
    plot_hours(hours)
    plot_cells(cells, "Median bus speed by area, all hours collected", "speed_map.png")
    slowest = cells[cells.buses >= 10].nsmallest(10, "median_kmh")
    summary = {
        "steps": int(len(df)),
        "buses": int(df.vehicle_id.nunique()),
        "time_span": [str(df.time.min()), str(df.time.max())],
        "median_speed_kmh": round(float(df.speed_kmh.median()), 1),
        "share_steps_below_5_kmh": round(float((df.speed_kmh < 5).mean()), 3),
        "cells_mapped": int(len(cells)),
        "by_hour": hours.reset_index().to_dict("records"),
        "slowest_cells": slowest[["lat", "lon", "median_kmh", "buses"]].round(4).to_dict("records"),
    }
    SUMMARY.write_text(json.dumps(summary, indent=2), "utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "by_hour"}, indent=2))
    print(hours.to_string())


if __name__ == "__main__":
    main()
