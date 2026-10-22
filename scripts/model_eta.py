"""Predict how long a bus takes to reach each of its next 1 to 10 stops.

Compares two baselines with a LightGBM model on a time-based split: the first 75% of the
collection window trains, the last 25% tests.

Usage:
    python scripts/model_eta.py
"""

import json
from pathlib import Path

import lightgbm as lgb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
FIGURES = ROOT / "docs" / "figures"
SUMMARY = ROOT / "docs" / "model_summary.json"

HORIZONS = range(1, 11)
TRAIN_SHARE = 0.75
BLOCK_S = 1800            # block length for the same-hours split
LIVE_WINDOW = 5           # recent traversals averaged for the live segment speed
MAX_HOP_S = 600           # a single stop-to-stop hop longer than this is a halt, not traffic
EARTH_RADIUS_M = 6_371_000


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def route_geometry():
    routes = pd.read_parquet(PROCESSED / "routes.parquet").sort_values(["route_id", "seq"])
    previous = routes.groupby("route_id")[["stop_lat", "stop_lon"]].shift()
    step = haversine_m(previous.stop_lat, previous.stop_lon, routes.stop_lat, routes.stop_lon).fillna(0)
    routes["cum_m"] = step.groupby(routes.route_id).cumsum()
    routes["next_stop"] = routes.groupby("route_id").stop_id.shift(-1)
    return routes[["route_id", "stop_id", "seq", "cum_m", "next_stop"]]


def passages(routes):
    events = pd.read_parquet(PROCESSED / "stop_events.parquet")
    events["trip_key"] = events.vehicle_id + "|" + events.trip_id + "|" + events.start_date
    p = events.merge(routes, on=["route_id", "stop_id"]).sort_values(["trip_key", "arrival_ts"])
    # Drop passages that go backwards along the route; they are matching noise.
    p = p[p.seq > p.groupby("trip_key").seq.cummax().groupby(p.trip_key).shift().fillna(-1)]
    # Count halts (stop-to-stop hops over MAX_HOP_S) so examples that span one can be dropped.
    hop = p.arrival_ts - p.groupby("trip_key").arrival_ts.shift()
    p["halts"] = (hop > MAX_HOP_S).groupby(p.trip_key).cumsum()
    return p[["trip_key", "route_id", "stop_id", "next_stop", "seq", "cum_m", "arrival_ts", "halts"]].reset_index(drop=True)


def live_segment_speeds(p):
    """For each segment, the mean speed of the last few buses that finished it."""
    nxt = p.groupby("trip_key")[["seq", "cum_m", "arrival_ts"]].shift(-1)
    seg = p.assign(end_ts=nxt.arrival_ts, length=nxt.cum_m - p.cum_m)
    seg = seg[(nxt.seq == p.seq + 1) & (seg.end_ts > seg.arrival_ts) & (seg.length > 0)
              & (seg.end_ts - seg.arrival_ts <= MAX_HOP_S)].copy()
    seg["speed"] = seg.length / (seg.end_ts - seg.arrival_ts)
    seg["segment"] = seg.stop_id + ">" + seg.next_stop
    seg = seg.sort_values("end_ts")
    seg["live_speed"] = seg.groupby("segment").speed.transform(lambda s: s.rolling(LIVE_WINDOW, min_periods=1).mean())
    return seg[["segment", "end_ts", "live_speed"]]


def own_speed(p):
    """Each bus's speed over its previous (up to) three stops."""
    group = p.groupby("trip_key")
    back = group[["cum_m", "arrival_ts"]].shift(3)
    for n in (2, 1):
        fallback = group[["cum_m", "arrival_ts"]].shift(n)
        back = back.fillna(fallback)
    elapsed = p.arrival_ts - back.arrival_ts
    return ((p.cum_m - back.cum_m) / elapsed).where(elapsed > 0)


def examples(p, live):
    p = p.assign(own_speed=own_speed(p), segment=p.stop_id + ">" + p.next_stop.fillna(""))
    # Live speed on the next segment, using only buses that finished it before this bus reached the stop.
    p = pd.merge_asof(p.sort_values("arrival_ts"), live.rename(columns={"end_ts": "live_ts"}),
                      left_on="arrival_ts", right_on="live_ts", by="segment", allow_exact_matches=False)
    p["live_age_s"] = p.arrival_ts - p.live_ts
    target = p[["trip_key", "seq", "cum_m", "arrival_ts", "halts"]]
    rows = []
    for h in HORIZONS:
        ahead = target.assign(seq=target.seq - h).rename(
            columns={"cum_m": "dest_cum_m", "arrival_ts": "dest_ts", "halts": "dest_halts"})
        rows.append(p.merge(ahead, on=["trip_key", "seq"]).assign(horizon=h))
    df = pd.concat(rows, ignore_index=True)
    df = df[df.dest_halts == df.halts]
    df["distance_m"] = df.dest_cum_m - df.cum_m
    df["travel_s"] = df.dest_ts - df.arrival_ts
    df = df[(df.travel_s > 0) & (df.distance_m > 0) & (df.distance_m / df.travel_s < 80 / 3.6)]
    local = pd.to_datetime(df.arrival_ts, unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
    df["hour"] = local.dt.hour + local.dt.minute / 60
    return df


def split(df):
    cutoff = df.arrival_ts.quantile(TRAIN_SHARE)
    # Training targets must also finish before the cutoff, so no future information leaks in.
    train = df[df.dest_ts < cutoff]
    test = df[df.arrival_ts >= cutoff]
    return train, test, cutoff


def same_hours_split(df):
    """Alternate 30-minute blocks, so training and testing cover the same times of evening."""
    start = df.arrival_ts.min()
    block = ((df.arrival_ts - start) // BLOCK_S).astype(int)
    inside = block == ((df.dest_ts - start) // BLOCK_S).astype(int)
    return df[inside & (block % 2 == 0)], df[inside & (block % 2 == 1)]


def unseen_routes_split(df):
    """Hold out a quarter of the routes entirely, over the same hours."""
    routes = pd.Series(df.route_id.unique())
    held_out = set(routes.sample(frac=0.25, random_state=0))
    test_mask = df.route_id.isin(held_out)
    return df[~test_mask], df[test_mask]


def baselines(train, test):
    speed = (train.distance_m / train.travel_s).median()
    # Fall back from route and stop history, to stop history alone, to distance at the typical speed.
    by_route = train.groupby(["route_id", "stop_id", "horizon"]).travel_s.median().rename("route_s")
    by_stop = train.groupby(["stop_id", "horizon"]).travel_s.median().rename("stop_s")
    joined = test.join(by_route, on=["route_id", "stop_id", "horizon"]).join(by_stop, on=["stop_id", "horizon"])
    pred_hist = joined["route_s"].fillna(joined["stop_s"]).fillna(test.distance_m / speed)
    own = test.own_speed.clip(1, 60 / 3.6)
    pred_own = (test.distance_m / own).fillna(pred_hist)
    return pred_hist, pred_own


FEATURES = ["horizon", "distance_m", "hour", "own_speed", "live_speed", "live_age_s", "route_id", "stop_id"]


def fit_model(train, test):
    data = pd.concat([train, test])
    for column in ("route_id", "stop_id"):
        data[column] = data[column].astype("category")
    x_train, x_test = data.loc[train.index, FEATURES], data.loc[test.index, FEATURES]
    model = lgb.LGBMRegressor(objective="l1", n_estimators=600, learning_rate=0.05, num_leaves=63,
                              min_child_samples=50, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                              verbose=-1, random_state=0)
    model.fit(x_train, train.travel_s)
    importance = pd.Series(model.booster_.feature_importance("gain"), index=FEATURES)
    return model.predict(x_test), (importance / importance.sum()).round(3)


def score(test, prediction):
    error = (prediction - test.travel_s).abs()
    by_h = error.groupby(test.horizon).mean().round(1)
    return {"mae_s": round(float(error.mean()), 1),
            "within_60s": round(float((error <= 60).mean()), 3),
            "within_120s": round(float((error <= 120).mean()), 3),
            "mae_by_horizon_s": by_h.to_dict()}


def plot(results):
    fig, ax = plt.subplots(figsize=(8, 3.8))
    colours = {"Historical median": "#94a3b8", "Own recent speed": "#f59e0b", "LightGBM": "#2563eb"}
    for name, result in results.items():
        h = result["mae_by_horizon_s"]
        ax.plot(list(h.keys()), list(h.values()), marker="o", label=name, color=colours[name])
    ax.set_xlabel("Stops ahead")
    ax.set_ylabel("Mean absolute error (s)")
    ax.set_xticks(list(HORIZONS))
    ax.set_title("Arrival-time error on the held-out last quarter of the evening")
    ax.legend(frameon=False)
    fig.savefig(FIGURES / "eta_error_by_horizon.png", dpi=130, bbox_inches="tight")
    plt.close(fig)


def evaluate(train, test):
    pred_hist, pred_own = baselines(train, test)
    pred_model, importance = fit_model(train, test)
    results = {"Historical median": score(test, pred_hist), "Own recent speed": score(test, pred_own),
               "LightGBM": score(test, pred_model)}
    return results, importance


def main():
    routes = route_geometry()
    p = passages(routes)
    df = examples(p, live_segment_speeds(p))
    train, test, cutoff = split(df)
    results, importance = evaluate(train, test)
    plot(results)
    robustness = {}
    for name, (tr, te) in {"same_hours": same_hours_split(df), "unseen_routes": unseen_routes_split(df)}.items():
        res, _ = evaluate(tr, te)
        robustness[name] = {"train": len(tr), "test": len(te),
                            **{method: {k: r[k] for k in ("mae_s", "within_60s", "within_120s")} for method, r in res.items()}}
    local_cutoff = pd.Timestamp(cutoff, unit="s", tz="UTC").tz_convert("Asia/Kolkata")
    summary = {"examples": len(df), "train": len(train), "test": len(test), "test_starts": f"{local_cutoff:%H:%M}",
               "median_travel_s": float(df.travel_s.median()), "results": results,
               "feature_importance": importance.to_dict(), "robustness": robustness}
    SUMMARY.write_text(json.dumps(summary, indent=2), "utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("results", "robustness")}, indent=2))
    for name, result in results.items():
        print(f"{name:18} MAE {result['mae_s']:6.1f} s  within 60 s {result['within_60s']:.1%}  within 120 s {result['within_120s']:.1%}")
    for split_name, res in robustness.items():
        print(f"\n{split_name}: train {res['train']:,}  test {res['test']:,}")
        for method in ("Historical median", "Own recent speed", "LightGBM"):
            print(f"  {method:18} MAE {res[method]['mae_s']:6.1f} s  within 120 s {res[method]['within_120s']:.1%}")


if __name__ == "__main__":
    main()
