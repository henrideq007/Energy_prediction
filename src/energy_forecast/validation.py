"""Data cleaning & validation.

Philosophy: price spikes and negative prices are REAL market events — they are
flagged, never deleted. Only physically impossible values are removed, and only
short gaps are interpolated.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

# SDAC harmonised clearing price limits (EUR/MWh). Check the current values on
# the NEMO Committee site — they are raised automatically after extreme events.
PRICE_BOUNDS = (-500.0, 5000.0)
MAX_INTERP_GAP_H = 3


@dataclass
class ValidationReport:
    n_rows: int = 0
    start: str = ""
    end: str = ""
    missing_timestamps: int = 0
    duplicate_timestamps: int = 0
    missing_pct: dict = field(default_factory=dict)
    out_of_bounds: dict = field(default_factory=dict)
    interpolated: dict = field(default_factory=dict)
    flagged_spikes: int = 0
    negative_price_hours: int = 0
    dropped_constant_cols: list = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            "# Data validation report",
            f"- Period: {self.start} → {self.end} ({self.n_rows:,} hourly rows)",
            f"- Missing timestamps (re-indexed): {self.missing_timestamps}",
            f"- Duplicate timestamps (dropped): {self.duplicate_timestamps}",
            f"- Negative-price hours: {self.negative_price_hours}",
            f"- Price spikes flagged (|robust z| > 6): {self.flagged_spikes}",
            f"- Constant columns dropped: {self.dropped_constant_cols or 'none'}",
            "",
            "| column | missing % (after cleaning) | out-of-bounds removed | short gaps interpolated |",
            "|---|---|---|---|",
        ]
        for c, v in sorted(self.missing_pct.items(), key=lambda x: -x[1]):
            lines.append(f"| {c} | {v:.2f} | {self.out_of_bounds.get(c, 0)} | {self.interpolated.get(c, 0)} |")
        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, default=str)


def _bounds(col: str) -> tuple[float, float] | None:
    if col.startswith("price_da"):
        return PRICE_BOUNDS
    if col.startswith(("load_", "gen_", "fc_")):
        return (0.0, 30000.0)  # BE peak load is ~14 GW; generous upper bound
    if col.endswith("temperature_2m"):
        return (-30.0, 45.0)
    if col.endswith(("shortwave_radiation",)):
        return (0.0, 1400.0)
    if col.endswith("cloud_cover"):
        return (0.0, 100.0)
    if "wind_speed" in col:
        return (0.0, 200.0)
    return None


def interpolate_short_gaps(s: pd.Series, max_gap: int) -> pd.Series:
    """Time-interpolate only the gaps of at most `max_gap` consecutive missing values (inside the series)."""
    na = s.isna()
    if not na.any():
        return s
    run_id = (na != na.shift()).cumsum()
    run_len = na.groupby(run_id).transform("size")
    short = na & (run_len <= max_gap)
    interp = s.interpolate(method="time", limit_area="inside")
    return s.where(~short, interp)


def clean_and_validate(df: pd.DataFrame, price_col: str = "price_da") -> tuple[pd.DataFrame, ValidationReport]:
    rep = ValidationReport()
    df = df.copy()
    df.index = pd.DatetimeIndex(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")

    # 1. Index integrity: unique, sorted, continuous hourly grid in UTC (no DST issues)
    rep.duplicate_timestamps = int(df.index.duplicated().sum())
    df = df[~df.index.duplicated(keep="first")].sort_index()
    full = pd.date_range(df.index.min(), df.index.max(), freq="1h", tz="UTC")
    rep.missing_timestamps = int(len(full) - len(df))
    df = df.reindex(full)

    # 2. Drop columns with no information
    const = [c for c in df.columns if df[c].nunique(dropna=True) <= 1]
    rep.dropped_constant_cols = const
    df = df.drop(columns=const)

    # 3. Physical bounds -> NaN
    for c in df.columns:
        b = _bounds(c)
        if b is None:
            continue
        mask = (df[c] < b[0]) | (df[c] > b[1])
        if mask.any():
            rep.out_of_bounds[c] = int(mask.sum())
            df.loc[mask, c] = np.nan

    # 4. Interpolate only short gaps (<= 3h). Long gaps stay ENTIRELY NaN (models handle / rows dropped).
    #    Note: pandas' `limit=` alone would also fill the first 3 hours of every long gap.
    for c in df.columns:
        filled_s = interpolate_short_gaps(df[c], MAX_INTERP_GAP_H)
        filled = int(df[c].isna().sum() - filled_s.isna().sum())
        df[c] = filled_s
        if filled:
            rep.interpolated[c] = filled

    # 5. Flag (do not remove) price spikes with a robust rolling z-score
    if price_col in df:
        p = df[price_col]
        med = p.rolling(24 * 28, min_periods=24 * 7, center=True).median()
        mad = (p - med).abs().rolling(24 * 28, min_periods=24 * 7, center=True).median()
        z = (p - med) / (1.4826 * mad.replace(0, np.nan))
        df["flag_price_spike"] = (z.abs() > 6).astype(int)
        rep.flagged_spikes = int(df["flag_price_spike"].sum())
        rep.negative_price_hours = int((p < 0).sum())

    rep.n_rows = len(df)
    rep.start, rep.end = str(df.index.min()), str(df.index.max())
    rep.missing_pct = {c: float(df[c].isna().mean() * 100) for c in df.columns}
    return df, rep
