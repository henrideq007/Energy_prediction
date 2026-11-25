"""Exploratory data analysis helpers (T11): price regimes, daily profiles, negative prices,
merit order and driver correlations.

All functions are small and pure: they take a DataFrame indexed in **Europe/Brussels local
time** (use :func:`to_local`) and return new objects. Plotting helpers return a matplotlib
``Figure`` and never call ``plt.show()``. Descriptive only — nothing here is used by the models.

Leakage note: the EDA may *describe* the ENTSO-E ``fc_*`` series (Elia's 6PM run, published
~18:00 D-1), but they are baseline-only and must never become features (D-16 / D-29).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PRICE_COL = "price_da"
SPIKE_FLAG_COL = "flag_price_spike"   # set by validation.clean (|robust rolling z| > 6, both tails)
# `ttf_gas` is NOT TTF for most of the history (D-25, DATA_SOURCES rows 3/3c/3d): IMF monthly EU
# gas proxy 2019 -> Sep 2021 (flag_gas_monthly_proxy = 1), THE VTP daily price from Oct 2021, real
# Yahoo TTF closes only recently. Call it "gas price" in outputs.
GAS_COL = "ttf_gas"
GAS_PROXY_FLAG_COL = "flag_gas_monthly_proxy"
GAS_LABEL = "gas price (ttf_gas)"

# --- Price regimes ---------------------------------------------------------------------------
# Boundaries are local dates (start inclusive). Justification:
# - 2021-07-01: the gas price (`ttf_gas`: IMF monthly EU proxy to Sep 2021, D-25) leaves its
#   2019-2020 range (~10-25 EUR/MWh) in summer 2021 and BE monthly mean prices more than
#   double between June and September 2021.
# - 2023-07-01: after the winter 2022/23 the gas price (`ttf_gas`: THE VTP daily since Oct 2021,
#   D-25) falls back to ~30-40 EUR/MWh (Q2 2023) and BE monthly prices stabilise around
#   80-100 EUR/MWh; the extreme volatility of 2022 is gone.
# These are round, documented cut points for description — not estimated change points.
REGIMES: dict[str, str] = {
    "pre_crisis": "2019-01-01",
    "crisis": "2021-07-01",
    "post_crisis": "2023-07-01",
}
REGIME_ORDER: list[str] = list(REGIMES)

SEASONS: dict[int, str] = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring",
                           5: "spring", 6: "summer", 7: "summer", 8: "summer", 9: "autumn",
                           10: "autumn", 11: "autumn"}
SEASON_ORDER: list[str] = ["winter", "spring", "summer", "autumn"]

# Families kept out of features until an ablation test (D-24); `elia_` runs other than the
# day-ahead 11AM run are candidates too (handled in `core_driver_columns`).
CANDIDATE_PREFIXES: tuple[str, ...] = ("nb_", "unav_", "xch_", "fb_", "cap_BE_", "hydro_res_",
                                       "wfr_", "cmd_", "flag_")
ELIA_11H_SUFFIX = "_dayahead11hforecast"

# Residual-load inputs: preferred = information available at the D-1 11:00 issue time.
LOAD_FC_COL = "load_forecast"
ELIA_11H = {"wind": "elia_wind_dayahead11hforecast", "solar": "elia_solar_dayahead11hforecast"}
TSO_6PM = {"wind": "fc_wind", "solar": "fc_solar"}   # fallback for description only (D-29)

RL_BIN_EDGES_GW: np.ndarray = np.arange(-6.0, 15.0, 1.0)
MIN_BIN_COUNT = 50


# --- Basic transforms ------------------------------------------------------------------------
def to_local(df: pd.DataFrame, tz: str) -> pd.DataFrame:
    """Return a copy indexed in local time `tz` (index must be tz-aware)."""
    if df.index.tz is None:
        raise ValueError("index must be tz-aware (the dataset is stored in UTC)")
    out = df.copy()
    out.index = out.index.tz_convert(tz)
    return out


def label_regime(index: pd.DatetimeIndex, regimes: dict[str, str] | None = None) -> pd.Series:
    """Label each timestamp with its price regime (local dates, start inclusive)."""
    regimes = regimes or REGIMES
    names = list(regimes)
    labels = np.full(len(index), None, dtype=object)
    for name, start in sorted(regimes.items(), key=lambda kv: pd.Timestamp(kv[1])):
        labels[index >= pd.Timestamp(start, tz=index.tz)] = name
    return pd.Series(pd.Categorical(labels, categories=names, ordered=True), index=index,
                     name="regime")


def trim_to_valid(df: pd.DataFrame, col: str = PRICE_COL) -> pd.DataFrame:
    """Drop leading/trailing rows where `col` is NaN (other columns may run longer)."""
    first, last = df[col].first_valid_index(), df[col].last_valid_index()
    if first is None:
        return df.iloc[0:0]
    return df.loc[first:last]


def _log_outside_edges(values: pd.Series, edges: Sequence[float], what: str) -> int:
    """Log (and return) how many non-NaN values fall outside [edges[0], edges[-1]]."""
    v = values.dropna()
    n = int(((v < edges[0]) | (v > edges[-1])).sum())
    if n:
        logger.info("%s: %d values outside bin edges [%s, %s] dropped", what, n, edges[0], edges[-1])
    return n


def calendar_frame(index: pd.DatetimeIndex) -> pd.DataFrame:
    """Hour, month, year, season and weekday/weekend labels for a local-time index."""
    return pd.DataFrame({
        "hour": index.hour,
        "month": index.month,
        "year": index.year,
        "season": pd.Categorical(index.month.map(SEASONS), categories=SEASON_ORDER, ordered=True),
        "daytype": np.where(index.dayofweek >= 5, "weekend", "weekday"),
    }, index=index)


# --- Regime statistics -----------------------------------------------------------------------
def regime_summary(df: pd.DataFrame, price_col: str = PRICE_COL,
                   spike_col: str = SPIKE_FLAG_COL) -> pd.DataFrame:
    """Price statistics per regime: hours, mean, median, std, p5, p95, spike & negative shares (%)."""
    p = df[price_col]
    reg = label_regime(df.index)
    spikes = df[spike_col] if spike_col in df else pd.Series(np.nan, index=df.index)
    if spike_col not in df:
        logger.warning("%s missing: spike share left empty", spike_col)
    valid = p.notna()
    g = pd.DataFrame({"p": p, "spike": spikes, "neg": (p < 0).astype(float),
                      "regime": reg})[valid].groupby("regime", observed=True)
    out = pd.DataFrame({
        "start": g["p"].apply(lambda s: s.index.min().date()),
        "end": g["p"].apply(lambda s: s.index.max().date()),
        "hours": g["p"].size(),
        "mean": g["p"].mean(),
        "median": g["p"].median(),
        "std": g["p"].std(),
        "p5": g["p"].quantile(0.05),
        "p95": g["p"].quantile(0.95),
        "spike_share_pct": g["spike"].mean() * 100,
        "negative_share_pct": g["neg"].mean() * 100,
    })
    return out


def yearly_summary(df: pd.DataFrame, price_col: str = PRICE_COL) -> pd.DataFrame:
    """Mean/median/std price and negative-hour count per calendar year (local)."""
    p = df[price_col].dropna()
    g = p.groupby(p.index.year)
    return pd.DataFrame({"hours": g.size(), "mean": g.mean(), "median": g.median(),
                         "std": g.std(), "negative_hours": g.apply(lambda s: int((s < 0).sum())),
                         "min": g.min(), "max": g.max()}).rename_axis("year")


# --- Daily profiles --------------------------------------------------------------------------
def hourly_profile(df: pd.DataFrame, by: Sequence[str] = ("regime", "season"),
                   price_col: str = PRICE_COL, stat: str = "mean") -> pd.DataFrame:
    """Price profile by local hour: rows = hour (0-23), columns = groups in `by`.

    `by` may contain "regime", "season", "daytype", "month", "year".
    """
    cal = calendar_frame(df.index)
    cal["regime"] = label_regime(df.index)
    keys = [cal[k] for k in by] + [cal["hour"]]
    prof = df[price_col].groupby(keys, observed=True).agg(stat)
    return prof.unstack(list(range(len(by)))).sort_index()


def profile_shape(profile: pd.DataFrame) -> pd.DataFrame:
    """Shape descriptors of hourly profiles: peak/trough hour, values and peak-trough spread."""
    return pd.DataFrame({
        "peak_hour": profile.idxmax(), "peak": profile.max(),
        "trough_hour": profile.idxmin(), "trough": profile.min(),
        "spread": profile.max() - profile.min(),
    })


# --- Negative prices -------------------------------------------------------------------------
def negative_counts(df: pd.DataFrame, by: str, price_col: str = PRICE_COL) -> pd.Series:
    """Number of negative-price hours grouped by a calendar key ("year", "hour", "month")."""
    cal = calendar_frame(df.index)
    neg = (df[price_col] < 0) & df[price_col].notna()
    return neg.groupby(cal[by]).sum().astype(int).rename("negative_hours")


def negative_heatmap(df: pd.DataFrame, price_col: str = PRICE_COL,
                     since: str | None = None) -> pd.DataFrame:
    """Share (%) of negative-price hours, rows = local hour, columns = month."""
    d = df if since is None else df[df.index >= pd.Timestamp(since, tz=df.index.tz)]
    cal = calendar_frame(d.index)
    neg = (d[price_col] < 0).astype(float).where(d[price_col].notna())
    return (neg.groupby([cal["hour"], cal["month"]]).mean() * 100).unstack("month")


def negative_share_by_bins(df: pd.DataFrame, driver: pd.Series, edges: Sequence[float],
                           price_col: str = PRICE_COL) -> pd.DataFrame:
    """Share of negative-price hours conditional on bins of `driver` (aligned on df.index)."""
    p = df[price_col]
    ok = p.notna() & driver.notna()
    _log_outside_edges(driver[ok], edges, f"negative_share_by_bins({driver.name})")
    bins = pd.cut(driver[ok], bins=list(edges), include_lowest=True)
    g = (p[ok] < 0).groupby(bins, observed=False)
    return pd.DataFrame({"hours": g.size(), "negative_share_pct": g.mean() * 100,
                         "median_price": p[ok].groupby(bins, observed=False).median()})


# --- Merit order -----------------------------------------------------------------------------
def residual_load(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Residual load forecast (MW) = load_forecast − wind − solar forecasts.

    Uses the Elia day-ahead 11AM run (available at the issue time) and falls back, per hour and
    per technology, to the ENTSO-E `fc_*` series (Elia 6PM run) where the 11AM run is missing
    (Elia solar starts 2020-10). Returns (residual_load, source) where source is "elia_11h",
    "fc_fallback" or NaN. The fallback is acceptable for description only, never as a feature.
    """
    if LOAD_FC_COL not in df:
        raise KeyError(f"{LOAD_FC_COL} is required for the residual load")
    parts: list[pd.Series] = []
    fallback = pd.Series(False, index=df.index)
    for tech in ("wind", "solar"):
        pref = df[ELIA_11H[tech]] if ELIA_11H[tech] in df else pd.Series(np.nan, index=df.index)
        alt = df[TSO_6PM[tech]] if TSO_6PM[tech] in df else pd.Series(np.nan, index=df.index)
        used_alt = pref.isna() & alt.notna()
        fallback |= used_alt
        parts.append(pref.fillna(alt))
    rl = (df[LOAD_FC_COL] - parts[0] - parts[1]).rename("residual_load")
    src = pd.Series(np.where(fallback, "fc_fallback", "elia_11h"), index=df.index, dtype=object)
    src[rl.isna()] = np.nan
    n_fb = int((src == "fc_fallback").sum())
    if n_fb:
        logger.info("residual_load: %d hours use the fc_* (6PM run) fallback", n_fb)
    return rl, src.rename("rl_source")


def merit_order_bins(price: pd.Series, rl_mw: pd.Series, groups: pd.Series | None = None,
                     edges_gw: Sequence[float] = RL_BIN_EDGES_GW,
                     min_count: int = MIN_BIN_COUNT) -> pd.DataFrame:
    """Binned price vs residual load (GW): median, p25, p75, count per bin (and per group).

    Bins with fewer than `min_count` hours are dropped.
    """
    d = pd.DataFrame({"price": price, "rl_gw": rl_mw / 1000.0})
    d["group"] = "all" if groups is None else groups
    d = d.dropna()
    _log_outside_edges(d["rl_gw"], edges_gw, "merit_order_bins")
    d["bin"] = pd.cut(d["rl_gw"], bins=list(edges_gw))
    g = d.groupby(["group", "bin"], observed=True)
    out = pd.DataFrame({"rl_mid_gw": g["rl_gw"].median(), "median": g["price"].median(),
                        "p25": g["price"].quantile(0.25), "p75": g["price"].quantile(0.75),
                        "hours": g.size()})
    return out[out["hours"] >= min_count]


def merit_order_slope(price: pd.Series, rl_mw: pd.Series,
                      groups: pd.Series | None = None) -> pd.DataFrame:
    """OLS slope of price on residual load, in EUR/MWh per GW, with intercept, R² and n."""
    d = pd.DataFrame({"price": price, "rl_gw": rl_mw / 1000.0})
    d["group"] = "all" if groups is None else groups
    d = d.dropna()
    rows = {}
    for key, s in d.groupby("group", observed=True):
        if len(s) < 3 or s["rl_gw"].std() == 0:
            continue
        slope, intercept = np.polyfit(s["rl_gw"], s["price"], 1)
        r = np.corrcoef(s["rl_gw"], s["price"])[0, 1]
        rows[key] = {"slope_eur_per_gw": slope, "intercept": intercept, "r2": r**2,
                     "hours": len(s)}
    return pd.DataFrame.from_dict(rows, orient="index")


# --- Correlations ----------------------------------------------------------------------------
def gas_price_correlation_daily(df: pd.DataFrame, price_col: str = PRICE_COL,
                                gas_col: str = GAS_COL, flag_col: str = GAS_PROXY_FLAG_COL,
                                ) -> pd.DataFrame:
    """Pearson correlation of daily-mean price and daily-mean gas price, pooled and per regime,
    excluding hours where the gas value is the monthly proxy (flag = 1) or the price is NaN."""
    keep = df[price_col].notna() & df[gas_col].notna()
    if flag_col in df:
        keep &= df[flag_col].fillna(0) == 0
    d = df.loc[keep, [price_col, gas_col]].resample("D").mean().dropna()
    reg = label_regime(d.index)
    rows: dict[str, dict[str, object]] = {}
    for name, part in [("all", d), *((r, d[reg == r]) for r in REGIME_ORDER)]:
        if len(part) < 3:
            continue
        rows[name] = {"start": part.index.min().date(), "end": part.index.max().date(),
                      "days": len(part), "pearson": part[price_col].corr(part[gas_col])}
    return pd.DataFrame.from_dict(rows, orient="index")



def core_driver_columns(columns: Sequence[str], target: str = PRICE_COL) -> list[str]:
    """Columns that are not candidate families (D-24) nor the target itself."""
    out = []
    for c in columns:
        if c == target or c.startswith(CANDIDATE_PREFIXES):
            continue
        if c.startswith("elia_") and not c.endswith(ELIA_11H_SUFFIX):
            continue
        out.append(c)
    return out


def driver_availability(col: str) -> str:
    """How a column may be used at the D-1 11:00 issue time (descriptive label, D-05/D-16/D-29)."""
    if col.startswith("fc_"):
        return "baseline-only (6PM run)"
    if col.startswith("price_da"):
        return "lag >= 24h"
    if col.startswith(("gen_", "load_actual")):
        return "lag >= 48h"
    if col == GAS_COL:
        return "stored with 2-day lag (monthly proxy < Oct 2021)"
    if col == "eua_carbon":
        return "stored with 2-day lag"
    if col.startswith("w_"):
        return "same-time (ERA5 proxy)"
    if col == LOAD_FC_COL or col.endswith(ELIA_11H_SUFFIX):
        return "same-time"
    return "see DATA_SOURCES"


def price_correlations(df: pd.DataFrame, target: str = PRICE_COL,
                       drivers: Sequence[str] | None = None) -> pd.DataFrame:
    """Same-hour Pearson and Spearman correlations of `target` with core drivers, pooled and per
    regime (Pearson). Contemporaneous and descriptive — not the lags the model may use."""
    drivers = list(drivers) if drivers is not None else core_driver_columns(
        [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])], target)
    if not drivers:
        return pd.DataFrame()
    sub = df[[target, *drivers]]
    out = pd.DataFrame({
        "pearson": sub.corr()[target].drop(target),
        "spearman": sub.corr(method="spearman")[target].drop(target),
    })
    reg = label_regime(df.index)
    for name in REGIME_ORDER:
        part = sub[reg == name]
        if len(part) > 2:
            out[f"pearson_{name}"] = part.corr()[target].drop(target)
    out["availability"] = [driver_availability(c) for c in out.index]
    return out.reindex(out["pearson"].abs().sort_values(ascending=False).index)


# --- Reporting -------------------------------------------------------------------------------
def to_markdown_table(df: pd.DataFrame, floatfmt: str = ".1f", index: bool = True) -> str:
    """Render a DataFrame as a GitHub markdown table (no `tabulate` dependency)."""
    def fmt(v: object) -> str:
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else format(v, floatfmt)
        return str(v)

    idx_name = " / ".join(str(n) for n in df.index.names if n is not None) or ""
    header = ([idx_name] if index else []) + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for i, row in zip(df.index, df.itertuples(index=False)):
        cells = ([" / ".join(map(str, i)) if isinstance(i, tuple) else str(i)] if index else [])
        cells += [fmt(v) for v in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


# --- Plots -----------------------------------------------------------------------------------
def plot_weekly_price(df: pd.DataFrame, price_col: str = PRICE_COL, gas_col: str = GAS_COL):
    """Weekly mean price with regime shading (and the gas price on a twin axis if present)."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 4))
    w = df[price_col].resample("W").mean()
    ax.plot(w.index, w.values, lw=1, color="black", label="BE day-ahead (weekly mean)")
    colors = {"pre_crisis": "tab:green", "crisis": "tab:red", "post_crisis": "tab:blue"}
    bounds = [pd.Timestamp(s, tz=df.index.tz) for s in REGIMES.values()] + [df.index.max()]
    for i, name in enumerate(REGIME_ORDER):
        ax.axvspan(bounds[i], bounds[i + 1], color=colors.get(name, "grey"), alpha=0.08, label=name)
    ax.set_ylabel("EUR/MWh")
    if gas_col in df:
        ax2 = ax.twinx()
        g = df[gas_col].resample("W").mean()
        ax2.plot(g.index, g.values, lw=1, color="tab:orange", alpha=0.8, label=GAS_LABEL)
        ax2.set_ylabel("Gas price EUR/MWh (proxy < Oct 2021)", color="tab:orange")
    ax.legend(loc="upper left", fontsize=8)
    ax.set_title("BE day-ahead price (weekly mean) and price regimes")
    fig.tight_layout()
    return fig


def plot_profiles(profile: pd.DataFrame, title: str):
    """One panel per first-level column group; lines = remaining levels."""
    import matplotlib.pyplot as plt

    top = list(dict.fromkeys(profile.columns.get_level_values(0)))
    fig, axes = plt.subplots(1, len(top), figsize=(4.2 * len(top), 3.6), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, key in zip(axes, top):
        part = profile[key]
        part.columns = [" / ".join(map(str, c)) if isinstance(c, tuple) else str(c)
                        for c in part.columns]
        part.plot(ax=ax, lw=1.2)
        ax.set_title(str(key)); ax.set_xlabel("local hour"); ax.set_ylabel("EUR/MWh")
        ax.legend(fontsize=7)
    fig.suptitle(title)
    fig.tight_layout()
    return fig


def plot_heatmap(table: pd.DataFrame, title: str, cbar_label: str):
    """Simple heatmap (rows = index, columns = columns)."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(table.to_numpy(dtype=float), aspect="auto", origin="lower", cmap="viridis")
    ax.set_xticks(range(table.shape[1]), table.columns)
    ax.set_yticks(range(table.shape[0]), table.index)
    ax.set_xlabel(table.columns.name or ""); ax.set_ylabel(table.index.name or "")
    fig.colorbar(im, ax=ax, label=cbar_label)
    ax.set_title(title)
    fig.tight_layout()
    return fig


def plot_merit_order(bins: pd.DataFrame, title: str):
    """Binned median price (with p25-p75 band) vs residual load, one line per group."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.5))
    for key, part in bins.groupby(level=0, sort=False):
        part = part.droplevel(0)
        x = part["rl_mid_gw"].values
        ax.plot(x, part["median"].values, marker="o", ms=3, label=str(key))
        ax.fill_between(x, part["p25"].values, part["p75"].values, alpha=0.15)
    ax.set_xlabel("Residual load forecast (GW)"); ax.set_ylabel("Price (EUR/MWh)")
    ax.axhline(0, color="grey", lw=0.5)
    ax.legend(fontsize=8); ax.set_title(title)
    fig.tight_layout()
    return fig
