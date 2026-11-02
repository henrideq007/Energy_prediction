"""Small helpers shared by the data sources."""

from __future__ import annotations

import pandas as pd


def to_hourly_utc(obj: pd.Series | pd.DataFrame) -> pd.Series | pd.DataFrame:
    """Convert to a UTC, hourly-mean time series.

    Day-ahead prices switched from 60-min to 15-min MTU on 2025-10-01, and some
    ENTSO-E series are published at 15-min resolution. Averaging to hourly keeps
    one consistent grain across the full history.
    """
    if obj is None or len(obj) == 0:
        return obj
    out = obj.copy()
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out.resample("1h").mean()


def month_chunks(start: pd.Timestamp, end: pd.Timestamp, months: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Split [start, end) into windows of `months` months."""
    chunks = []
    cur = start
    while cur < end:
        nxt = min(cur + pd.DateOffset(months=months), end)
        chunks.append((cur, nxt))
        cur = nxt
    return chunks


def snake(name: str) -> str:
    return (
        name.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("/", "_")
        .replace("(", "")
        .replace(")", "")
    )
