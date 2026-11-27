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

Candidate families (`nb_`, `unav_`, `xch_`, `fb_`, `cap_BE_`, `hydro_res_`, other `elia_` runs, `wfr_`,
`cmd_`) stay OUT of the default matrix (D-24). `candidate_features()` (T45) builds them on request,
with the publication lags of `config.yaml > candidate_features`, for the D-15 ablation.
`CANDIDATE_MIN_LAG_H` is the hard safety floor that `leakage_check()` enforces whatever the config says.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence

import holidays
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

KNOWN_AHEAD_PREFIXES = ("load_forecast", "w_", "ttf_gas", "eua_carbon")
# Elia's wind/solar forecast run published at 11:00 D-1 = known at the 11:00 issue time (D-29)
KNOWN_AHEAD_COLUMNS = ("elia_wind_dayahead11hforecast", "elia_solar_dayahead11hforecast",
                       "elia_solar_dayahead11h_p10", "elia_solar_dayahead11h_p90")
WIND_FC, SOLAR_FC = "elia_wind_dayahead11hforecast", "elia_solar_dayahead11hforecast"
# Published after the issue time -> never a feature, only the input of the `tso_forecast` baseline (D-29)
BASELINE_ONLY_PREFIXES = ("fc_",)
PRICE_LAGS = (24, 48, 72, 168)
ACTUAL_LAGS = (48, 72, 168)

# --------------------------------------------------------------------------- candidates (T45)
CANDIDATE_PREFIXES = ("nb_", "unav_", "xch_", "fb_", "cap_BE_", "hydro_res_", "elia_", "wfr_", "cmd_", "nuc_")

# Hydro reservoirs (DP-044): weekly value of week W, forward-filled hourly. Observed value-change stamps
# (local Brussels time, dataset of Nov 2026) - FR: Monday 01:00 x210, Monday 00:00 x175, Sunday 23:00 x19;
# CH: Monday 01:00 x243, Monday 00:00 x164 (mostly Sunday 23:00 UTC = Monday 00:00 CET all year).
# Earliest stamp = Sunday 23:00 = 1 h before Monday 00:00 local; any later stamp (e.g. Tuesday) is safer.
# ENTSO-E publishes it the week after; assumption (unverified, T53): out at the latest at the END of the
# Thursday after W ends = Monday 00:00 of W + 11 days.
HYDRO_PUBLICATION_DELAY_H = 11 * 24   # Monday 00:00 of W -> Friday 00:00 of W+1
HYDRO_STAMP_EARLY_H = 1               # earliest observed stamp: Sunday 23:00 local, 1 h before Monday 00:00
MAX_ISSUE_LEAD_H = 37                 # t - issue(t): 13 h (D 00:00) .. 36 h (D 23:00), 37 h on a 25-h day


def hydro_min_safe_lag_h(publication_delay_h: int = HYDRO_PUBLICATION_DELAY_H,
                         stamp_early_h: int = HYDRO_STAMP_EARLY_H, max_issue_lead_h: int = MAX_ISSUE_LEAD_H) -> int:
    """Smallest shift h such that the week value used at row t was published before issue(t).

    Worst case: row t = stamp + h is the first row using a week value and is the last hour of its delivery
    day, so issue(t) = t - max_issue_lead_h. Need issue(t) >= publication = (stamp + stamp_early_h) + delay.
    This bound holds for any stamp from Sunday 23:00 local on; simulated hour by hour with stamps on
    Sunday 23:00 / Monday 00:00 / Monday 01:00 the exact minimum is 290 h (tests/test_candidate_features.py).
    Config uses 336 h (14 days).
    """
    return publication_delay_h + stamp_early_h + max_issue_lead_h   # 264 + 1 + 37 = 302 h


# Hard safety floor (h) per candidate column (first match wins). Independent of config.yaml on purpose:
# a too-short lag in the config raises in candidate_features() and is flagged by leakage_check().
CANDIDATE_MIN_LAG_H: tuple[tuple[str, int], ...] = (
    (r"^xch_", 48),                                   # scheduled exchanges may include ID renominations
    (r"^nb_.+_(load_actual|gen_nuclear)$", 48),       # neighbour actuals, as BE actuals (D-05)
    (r"^nb_.+_(load_fc|fc_.+)$", 24),                 # neighbour forecasts: D-1 forecast out by D-2 18:00
    (r"^fb_", 24),                                    # JAO flow-based domain, same-time pending T53
    (r"^unav_.+_nuclear_mw$", 0),                     # already "as known at the issue time" (D-27)
    (r"^nuc_BE_gap_proxy$", 48),                      # built from gen_nuclear (actual)
    (r"^cap_BE_", 0),                                 # yearly installed capacity, published before the year
    (r"^hydro_res_", hydro_min_safe_lag_h()),         # weekly, published the week after
    (r"^wfr_", 0),                                    # weather, same treatment as w_
    (r"^elia_.+_weekaheadforecast$", 24),             # publication time unverified (D-16): same-time pending T53
    (r"^elia_.+_dayaheadforecast$", 24),              # latest DA run, published after 11:00 D-1
    (r"^elia_.+_measured$", 48),                      # estimated actuals
    (r"^cmd_gas_storage", 48),                        # AGSI: gas day X out ~18:00 CET X+1 and revised later;
                                                      # stamped X+2 00:00 UTC -> lag 0 would use D-2 (out after issue)
    (r"^cmd_", 0),                                    # market closes already shifted by commodities.publication_lag_days
)
_LAG_SUFFIX = re.compile(r"^(?P<base>.+)_lag(?P<h>\d+)$")


def _split_lag(col: str) -> tuple[str, int]:
    """`x_lag48` -> ("x", 48); `x` -> ("x", 0)."""
    m = _LAG_SUFFIX.match(col)
    return (m["base"], int(m["h"])) if m else (col, 0)


def candidate_min_lag_h(col: str) -> int | None:
    """Safety floor for a raw candidate column, None if no rule covers it (= never allowed)."""
    for pattern, floor in CANDIDATE_MIN_LAG_H:
        if re.search(pattern, col):
            return floor
    return None


def issue_time(index: pd.DatetimeIndex, tz: str = "Europe/Brussels", issue_hour: int = 11) -> pd.DatetimeIndex:
    """Issue time (UTC) of the forecast covering each delivery hour: D-1 `issue_hour`:00 local (D-29)."""
    loc = index.tz_convert(tz).tz_localize(None).normalize()
    return (loc - pd.Timedelta(days=1) + pd.Timedelta(hours=issue_hour)).tz_localize(tz).tz_convert("UTC")


def nuclear_gap_proxy(df: pd.DataFrame, lag_h: int = 48) -> pd.Series:
    """BE nuclear available-capacity gap proxy: installed capacity - generation `lag_h` hours earlier.

    Leakage-safe (gen_nuclear is an actual -> lag >= 48 h) and available over the full history, unlike
    `unav_BE_nuclear_mw` (no ENTSO-E messages before 2022). Includes modulation and closures within a year.
    """
    return df["cap_BE_nuclear"] - df["gen_nuclear"].shift(lag_h)


PROXIES: dict[str, tuple[tuple[str, ...], Callable[[pd.DataFrame], pd.Series]]] = {
    "nuc_BE_gap_proxy_lag48": (("cap_BE_nuclear", "gen_nuclear"), lambda d: nuclear_gap_proxy(d, 48)),
}


def _mask_before(s: pd.Series, valid_from: str, tz: str) -> pd.Series:
    """NaN before local date `valid_from` (a value there means "unknown", e.g. no source coverage)."""
    return s.where(s.index >= pd.Timestamp(valid_from).tz_localize(tz))


def source_before_delivery_day(index: pd.DatetimeIndex, lag_h: int, tz: str = "Europe/Brussels") -> np.ndarray:
    """True where the source hour t - lag_h lies on a local date strictly before the delivery date of t.

    A row shift of 24 h is not "the previous day" on the 25-h autumn day: 23:00 - 24 h = 00:00 of the same
    day D, which is not known at the D-1 issue time. Such rows are masked in candidate_features().
    """
    return np.asarray(_local_date(index - pd.Timedelta(hours=lag_h), tz) < _local_date(index, tz))


def _local_date(index: pd.DatetimeIndex, tz: str) -> pd.DatetimeIndex:
    return index.tz_convert(tz).tz_localize(None).normalize()


def _lagged(s: pd.Series, h: int, tz: str) -> pd.Series:
    """Value at t - h (row shift on the hourly UTC grid), NaN where t - h is not before the delivery day."""
    if h == 0:
        return s
    lagged = s.shift(h)
    ok = source_before_delivery_day(s.index, h, tz)
    if not ok.all():
        log.debug("%s lag %s h: %s rows masked (source not before the delivery day, DST)", s.name, h, int((~ok).sum()))
    return lagged.where(ok)


def candidate_features(df: pd.DataFrame, families: Sequence[str], policy: Mapping[str, dict],
                       tz: str = "Europe/Brussels") -> pd.DataFrame:
    """Leakage-safe candidate columns for `families` (keys of `policy` = config `candidate_features`).

    Each family has `rules: [{pattern, lags_h}]`, optional `valid_from: {col: date}` and `proxies: [name]`.
    Output columns: `<col>` (lag 0) or `<col>_lag<h>` (value at t-h). Columns absent from df are skipped.
    Lagged values whose source hour is not on a local date before the delivery day (25-h DST day) are NaN.
    """
    unknown = [f for f in families if f not in policy]
    if unknown:
        raise ValueError(f"Unknown candidate family {unknown}; known: {sorted(policy)}")
    out: dict[str, pd.Series] = {}
    for fam in families:
        spec = policy[fam]
        valid_from = spec.get("valid_from") or {}
        for rule in spec.get("rules", []):
            cols = [c for c in df.columns if re.search(rule["pattern"], c)]
            if not cols:
                log.debug("Candidate family %s: no column matches %s", fam, rule["pattern"])
            for c in cols:
                floor = candidate_min_lag_h(c)
                s = _mask_before(df[c], valid_from[c], tz) if c in valid_from else df[c]
                for h in rule["lags_h"]:
                    if floor is None or h < floor:
                        raise ValueError(f"{fam}: lag {h} h for {c} is below its safety floor ({floor} h)")
                    out[c if h == 0 else f"{c}_lag{h}"] = _lagged(s, h, tz)
        for name in spec.get("proxies") or []:
            if name not in PROXIES:
                raise ValueError(f"{fam}: unknown proxy {name}; known: {sorted(PROXIES)}")
            needs, fn = PROXIES[name]
            if not set(needs).issubset(df.columns):
                log.debug("Candidate proxy %s skipped: needs %s", name, needs)
                continue
            out[name] = fn(df)
    return pd.DataFrame(out, index=df.index)


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
                   min_lag_prices: int = 24, candidate_families: Sequence[str] | None = None,
                   candidate_policy: Mapping[str, dict] | None = None) -> pd.DataFrame:
    """Return the feature matrix X (same index as df). Targets are NOT included.

    `candidate_families` (opt-in, T45): append `candidate_features()` for these families, with
    `candidate_policy` (default: `candidate_features` of config/config.yaml). None/[] = default matrix.
    """
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
    if candidate_families:
        if candidate_policy is None:
            from energy_forecast.config import load_config

            candidate_policy = load_config()["candidate_features"]
        cand = candidate_features(df, candidate_families, candidate_policy, tz)
        clash = [c for c in cand.columns if c in X.columns]
        if clash:
            log.warning("Candidate columns already in X, candidate version dropped: %s", clash)
        X = X.join(cand[[c for c in cand.columns if c not in clash]])
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
    """Return any column that looks like a same-time actual (should be empty).

    Candidate columns (T45) must carry at least the lag of `CANDIDATE_MIN_LAG_H`; a candidate column
    no rule covers is flagged too (except the Elia 11AM run, KNOWN_AHEAD_COLUMNS).
    """
    bad = []
    for c in X.columns:
        if c.startswith(("price_da", "load_actual", "gen_")) and "_lag" not in c and "_d1_" not in c \
                and "_d2_" not in c and "roll" not in c:
            bad.append(c)
        if c.startswith("flag_") or c.startswith(BASELINE_ONLY_PREFIXES):
            bad.append(c)
        if c.startswith(CANDIDATE_PREFIXES) and c not in KNOWN_AHEAD_COLUMNS:
            base, h = _split_lag(c)
            floor = candidate_min_lag_h(base)
            if floor is None or h < floor:
                bad.append(c)
    return bad
