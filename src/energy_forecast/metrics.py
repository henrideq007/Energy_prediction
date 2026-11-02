"""Evaluation metrics, including 'price movement' metrics for a 24h profile."""

from __future__ import annotations

import numpy as np
import pandas as pd


def mae(y, p):
    return float(np.mean(np.abs(np.asarray(y) - np.asarray(p))))


def rmse(y, p):
    return float(np.sqrt(np.mean((np.asarray(y) - np.asarray(p)) ** 2)))


def smape(y, p):
    y, p = np.asarray(y), np.asarray(p)
    denom = (np.abs(y) + np.abs(p)) / 2
    with np.errstate(divide="ignore", invalid="ignore"):
        v = np.where(denom == 0, 0, np.abs(y - p) / denom)
    return float(np.mean(v) * 100)


def direction_accuracy(y: pd.Series, p: pd.Series) -> float:
    """Share of hour-to-hour moves (within the forecast) whose sign is predicted correctly."""
    dy, dp = np.sign(y.diff()), np.sign(p.diff())
    m = dy.notna() & dp.notna() & (dy != 0)
    return float((dy[m] == dp[m]).mean()) if m.any() else np.nan


def peak_hour_hit(y: pd.Series, p: pd.Series, tz: str = "Europe/Brussels", tol_h: int = 1) -> float:
    """Share of days where the predicted most expensive hour is within ±tol_h of the real one."""
    df = pd.DataFrame({"y": y, "p": p})
    df["day"] = df.index.tz_convert(tz).date
    df["h"] = df.index.tz_convert(tz).hour
    hits = []
    for _, g in df.groupby("day"):
        if len(g) < 20:
            continue
        hits.append(abs(int(g.loc[g["y"].idxmax(), "h"]) - int(g.loc[g["p"].idxmax(), "h"])) <= tol_h)
    return float(np.mean(hits)) if hits else np.nan


def all_metrics(y: pd.Series, p: pd.Series, y_naive: pd.Series | None = None, tz: str = "Europe/Brussels") -> dict:
    out = {
        "MAE": mae(y, p),
        "RMSE": rmse(y, p),
        "sMAPE": smape(y, p),
        "DirAcc": direction_accuracy(y, p),
        "PeakHit": peak_hour_hit(y, p, tz),
    }
    if y_naive is not None:
        m = y_naive.notna()
        out["rMAE"] = mae(y[m], p[m]) / mae(y[m], y_naive[m]) if m.any() else np.nan
    return out
