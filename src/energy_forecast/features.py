"""Feature engineering with strict information-availability rules.

Forecast setting (see docs/METHODOLOGY.md): forecasts for delivery day D are
issued on D-1 at 11:00 Europe/Brussels (decision D-29), before the 12:00 SDAC gate closure.
At that moment we know:
  * all day-ahead prices up to and including D-1   -> price lags >= 24h
  * actual load / generation only up to ~D-1 10:00 -> actual lags >= 48h
  * TSO day-ahead load forecast for D (A65)          -> same-time feature
  * Elia wind/solar "day-ahead 11AM" run for D       -> same-time features (D-29)
  * weather forecasts for D                            -> same-time features
  * commodity closes up to D-2 (already shifted in data/commodities.py)
NOT known: ENTSO-E A69/A71 day-ahead forecasts (`fc_*`) = Elia's 6PM run, published ~18:00 D-1
(D-29). They are kept out of the feature matrix and only feed the `tso_forecast` baseline.
Each row t of the output describes delivery hour t; the target is y(t).
"""

from __future__ import annotations

import holidays
import numpy as np
import pandas as pd

KNOWN_AHEAD_PREFIXES = ("load_forecast", "w_", "ttf_gas", "eua_carbon")
# Elia's wind/solar forecast run published at 11:00 D-1 = known at the 11:00 issue time (D-29)
KNOWN_AHEAD_COLUMNS = ("elia_wind_dayahead11hforecast", "elia_solar_dayahead11hforecast",
                       "elia_solar_dayahead11h_p10", "elia_solar_dayahead11h_p90")
WIND_FC, SOLAR_FC = "elia_wind_dayahead11hforecast", "elia_solar_dayahead11hforecast"
# Published after the issue time -> never a feature, only the input of the `tso_forecast` baseline (D-29)
BASELINE_ONLY_PREFIXES = ("fc_",)
PRICE_LAGS = (24, 48, 72, 168)
ACTUAL_LAGS = (48, 72, 168)


def _calendar(index: pd.DatetimeIndex, tz: str) -> pd.DataFrame:
    loc = index.tz_convert(tz)
    years = range(loc.year.min(), loc.year.max() + 2)
    be_holidays = holidays.Belgium(years=years)
    out = pd.DataFrame(index=index)
    out["hour"] = loc.hour
    out["dow"] = loc.day_of_week
    out["month"] = loc.month
    out["is_weekend"] = (loc.day_of_week >= 5).astype(int)
    out["is_holiday"] = np.array([d in be_holidays for d in loc.date], dtype=int)
    out["doy_sin"] = np.sin(2 * np.pi * loc.day_of_year / 365.25)
    out["doy_cos"] = np.cos(2 * np.pi * loc.day_of_year / 365.25)
    out["hour_sin"] = np.sin(2 * np.pi * loc.hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * loc.hour / 24)
    return out


def _daily_stats(s: pd.Series, tz: str, shift_days: int, name: str) -> pd.DataFrame:
    """Stats of a full local day, attached to rows `shift_days` later (e.g. D-1 stats on day D)."""
    local_date = s.index.tz_convert(tz).normalize().tz_localize(None)
    daily = s.groupby(local_date).agg(["mean", "min", "max", "std"])
    daily.index = daily.index + pd.Timedelta(days=shift_days)
    mapped = daily.reindex(local_date)
    mapped.index = s.index
    return mapped.add_prefix(f"{name}_d{shift_days}_")


def build_features(df: pd.DataFrame, tz: str = "Europe/Brussels", min_lag_actuals: int = 48,
                   min_lag_prices: int = 24) -> pd.DataFrame:
    """Return the feature matrix X (same index as df). Targets are NOT included."""
    feats: list[pd.DataFrame] = [_calendar(df.index, tz)]

    price_cols = [c for c in df.columns if c.startswith("price_da")]
    actual_cols = [c for c in df.columns if c.startswith(("load_actual", "gen_"))]

    lagged = {}
    for c in price_cols:
        for lag in PRICE_LAGS:
            if lag >= min_lag_prices and (c == "price_da" or lag in (24, 168)):
                lagged[f"{c}_lag{lag}"] = df[c].shift(lag)
    for c in actual_cols:
        for lag in ACTUAL_LAGS:
            if lag >= min_lag_actuals:
                lagged[f"{c}_lag{lag}"] = df[c].shift(lag)
    feats.append(pd.DataFrame(lagged, index=df.index))

    if "price_da" in df:
        feats.append(_daily_stats(df["price_da"], tz, 1, "price_da"))
        p = df["price_da"].shift(min_lag_prices)
        feats.append(pd.DataFrame({
            "price_da_roll7d_mean": p.rolling(168, min_periods=24).mean(),
            "price_da_roll7d_std": p.rolling(168, min_periods=24).std(),
            "price_da_roll28d_mean": p.rolling(24 * 28, min_periods=24 * 7).mean(),
        }, index=df.index))
    if "load_actual" in df:
        feats.append(_daily_stats(df["load_actual"], tz, 2, "load_actual")[["load_actual_d2_mean", "load_actual_d2_max"]])

    # Same-time information that is genuinely known before the auction
    known = [c for c in df.columns if c.startswith(KNOWN_AHEAD_PREFIXES) or c in KNOWN_AHEAD_COLUMNS]
    feats.append(df[known])

    X = pd.concat(feats, axis=1)
    # Fundamental drivers: residual load = what conventional plants must cover
    # leakage-safe inputs only (Elia 11AM run); NaN where Elia has no history (solar before Oct 2020)
    if {"load_forecast", SOLAR_FC, WIND_FC}.issubset(df.columns):
        res = df[SOLAR_FC] + df[WIND_FC]
        X["residual_load_fc"] = df["load_forecast"] - res
        X["res_share_fc"] = res / df["load_forecast"]
    if {"ttf_gas", "eua_carbon"}.issubset(df.columns):
        # Approx. short-run marginal cost of a CCGT (efficiency ~50%, 0.37 tCO2/MWh_el)
        X["ccgt_srmc"] = df["ttf_gas"] / 0.5 + 0.37 * df["eua_carbon"]
    return X


def make_xy(df: pd.DataFrame, target: str, tz: str = "Europe/Brussels", **kw) -> tuple[pd.DataFrame, pd.Series]:
    X = build_features(df, tz=tz, **kw)
    y = df[target]
    mask = y.notna()
    return X.loc[mask], y.loc[mask]


def baseline_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Columns only the `tso_forecast` baseline may read (published after the issue time, D-29)."""
    return df[[c for c in df.columns if c.startswith(BASELINE_ONLY_PREFIXES)]]


def with_baseline_columns(X: pd.DataFrame, df: pd.DataFrame, model_name: str) -> pd.DataFrame:
    """X for `model_name`: the TSO baseline also gets the `fc_*` columns; learning models never do."""
    if model_name != "tso_forecast":
        return X
    b = baseline_frame(df).reindex(X.index)
    return X.join(b[[c for c in b.columns if c not in X.columns]])


def leakage_check(X: pd.DataFrame) -> list[str]:
    """Return any column that looks like a same-time actual (should be empty)."""
    bad = []
    for c in X.columns:
        if c.startswith(("price_da", "load_actual", "gen_")) and "_lag" not in c and "_d1_" not in c \
                and "_d2_" not in c and "roll" not in c:
            bad.append(c)
        if c.startswith("flag_") or c.startswith(BASELINE_ONLY_PREFIXES):
            bad.append(c)
    return bad
