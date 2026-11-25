"""Run the T11 exploratory analysis on the real dataset and write `reports/eda/`.

    python scripts/run_eda.py [--dataset data/processed/dataset_clean.parquet]

Outputs `reports/eda/eda_summary.md` (tables) and a few PNG figures. A hand-written
"Key insights" section between the INSIGHTS markers is preserved when the report is regenerated.
Descriptive only: nothing here feeds the models.
"""

from __future__ import annotations

import argparse
import logging
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from energy_forecast import eda
from energy_forecast.config import load_config

logger = logging.getLogger("run_eda")
DPI = 100
INSIGHTS_START = "<!-- INSIGHTS:START -->"
INSIGHTS_END = "<!-- INSIGHTS:END -->"
INSIGHTS_PLACEHOLDER = "_To be written by hand from the tables below (kept on regeneration)._"


def _save(fig, path: Path) -> None:
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    logger.info("wrote %s", path)


def _existing_insights(path: Path) -> str:
    if not path.exists():
        return INSIGHTS_PLACEHOLDER
    m = re.search(re.escape(INSIGHTS_START) + r"\n(.*?)\n" + re.escape(INSIGHTS_END),
                  path.read_text(encoding="utf-8"), flags=re.DOTALL)
    return m.group(1) if m else INSIGHTS_PLACEHOLDER


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(cfg.path("processed_dir") / "dataset_clean.parquet"))
    ap.add_argument("--out", default=str(cfg.path("reports_dir") / "eda"))
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    raw = eda.to_local(pd.read_parquet(a.dataset), cfg.tz)
    # Keep only the span where the price exists (other columns, e.g. gas, run a bit longer).
    df = eda.trim_to_valid(raw, eda.PRICE_COL)
    first, last = df.index.min(), df.index.max()
    logger.info("price span %s -> %s (%d of %d rows kept)", first, last, len(df), len(raw))
    T = eda.to_markdown_table
    md: list[str] = []

    # 1. Regimes
    reg_sum = eda.regime_summary(df)
    yearly = eda.yearly_summary(df)
    recent_cols = [c for c in ["price_da", "price_da_NL", "price_da_FR", "price_da_DE_LU",
                               eda.GAS_COL, "eua_carbon"] if c in df]
    recent = df[recent_cols].resample("MS").mean().tail(16)
    recent.index = recent.index.strftime("%Y-%m")
    recent.index.name = "month"
    _save(eda.plot_weekly_price(df), out / "weekly_price_regimes.png")

    # 2. Profiles
    prof_season = eda.hourly_profile(df, by=("regime", "season"))
    prof_daytype = eda.hourly_profile(df, by=("regime", "daytype"))
    shape_season = eda.profile_shape(prof_season)
    shape_daytype = eda.profile_shape(prof_daytype)
    _save(eda.plot_profiles(prof_season, "Mean hourly price by season, per regime"),
          out / "profiles_season.png")
    _save(eda.plot_profiles(prof_daytype, "Mean hourly price, weekday vs weekend, per regime"),
          out / "profiles_daytype.png")

    # 3. Negative prices
    neg_year = eda.negative_counts(df, "year")
    neg_hour = eda.negative_counts(df, "hour")
    neg_month = eda.negative_counts(df, "month")
    heat = eda.negative_heatmap(df, since="2023-07-01")
    _save(eda.plot_heatmap(heat, "Share of negative-price hours (%), Jul 2023 →", "% of hours"),
          out / "negative_heatmap_hour_month.png")
    post = df[eda.label_regime(df.index) == "post_crisis"]
    solar = post[eda.ELIA_11H["solar"]]
    wind = post[eda.ELIA_11H["wind"]]
    res_share = (solar + wind) / post[eda.LOAD_FC_COL] * 100
    neg_solar = eda.negative_share_by_bins(post, solar, [0, 500, 1000, 2000, 3000, 4000, 5000, 6000, 9000])
    neg_wind = eda.negative_share_by_bins(post, wind, [0, 500, 1000, 2000, 3000, 4000, 6000])
    neg_res = eda.negative_share_by_bins(post, res_share, [0, 20, 40, 60, 80, 100, 200])

    # 4. Merit order
    rl, src = eda.residual_load(df)
    fb_share = (src == "fc_fallback").mean() * 100
    fb_by_year = (src == "fc_fallback").groupby(df.index.year).sum()
    fb_text = ", ".join(f"{y}: {n:,} h" for y, n in fb_by_year.items() if n)
    regime = eda.label_regime(df.index)
    mo_bins = eda.merit_order_bins(df[eda.PRICE_COL], rl, regime)
    mo_slope = eda.merit_order_slope(df[eda.PRICE_COL], rl, regime)
    is_fb = (src == "fc_fallback") & df[eda.PRICE_COL].notna() & rl.notna()
    mo_slope["fc_fallback_hours"] = is_fb.groupby(regime, observed=True).sum()
    mo_pivot = mo_bins.reset_index().pivot(index="bin", columns="group", values="median")
    mo_pivot = mo_pivot.loc[sorted(mo_pivot.index, key=lambda iv: iv.left),
                            [r for r in eda.REGIME_ORDER if r in mo_pivot.columns]]
    _save(eda.plot_merit_order(mo_bins, "Merit order: price vs residual load forecast, per regime"),
          out / "merit_order_regimes.png")
    gas_edges = [0, 25, 50, 100, 400]
    gas_labels = ["gas<25", "gas 25-50", "gas 50-100", "gas>100"]
    gas_bins = pd.cut(df[eda.GAS_COL], gas_edges, labels=gas_labels)
    n_out = int((df[eda.GAS_COL].notna() & gas_bins.isna()).sum())
    if n_out:
        logger.info("gas bins: %d values outside %s dropped", n_out, gas_edges)
    mo_slope_gas = eda.merit_order_slope(df[eda.PRICE_COL], rl, gas_bins)
    if eda.GAS_PROXY_FLAG_COL in df:
        proxy = (df[eda.GAS_PROXY_FLAG_COL] == 1) & df[eda.PRICE_COL].notna() & rl.notna()
        mo_slope_gas["gas_proxy_hours"] = proxy.groupby(gas_bins, observed=True).sum()
    mo_bins_gas = eda.merit_order_bins(df[eda.PRICE_COL], rl, gas_bins)
    _save(eda.plot_merit_order(mo_bins_gas, "Merit order by gas price level (all years; "
                                            "IMF monthly proxy before Oct 2021)"),
          out / "merit_order_gas.png")
    gas_corr = eda.gas_price_correlation_daily(df)

    # 5. Correlations (core drivers only)
    corr = eda.price_correlations(df)

    # --- Markdown ---------------------------------------------------------------------------
    md += [
        "# EDA — Belgian day-ahead price (T11)",
        "",
        f"Generated by `python scripts/run_eda.py` on `{Path(a.dataset).name}` "
        f"({len(df):,} hours, {first:%Y-%m-%d} → {last:%Y-%m-%d}, Europe/Brussels local time). "
        "Descriptive statistics only — no causal claims, nothing here feeds the models.",
        "",
        "## Key insights (real data, 2019-01 → 2026-11)",
        "",
        INSIGHTS_START,
        _existing_insights(out / "eda_summary.md"),
        INSIGHTS_END,
        "",
        "## 1. Price regimes",
        "",
        "Regime boundaries (local dates, start inclusive; see `eda.REGIMES` for the justification): "
        + ", ".join(f"`{k}` from {v}" for k, v in eda.REGIMES.items()) + ". "
        "Spikes = `flag_price_spike` from `validation.clean` (|robust rolling 28-day z| > 6, "
        "both tails, so deep negative dips count as spikes too).",
        "",
        "**Gas price caveat (D-25).** `ttf_gas` is *not* TTF for most of the history: it is the IMF "
        "monthly EU gas proxy from 2019 to Sep 2021 (`flag_gas_monthly_proxy` = 1 up to "
        "2021-10-03), the THE VTP daily average (German hub) from Oct 2021, and Yahoo TTF closes "
        "only recently. It is called \"gas price\" below; pre-crisis gas statistics rest on a "
        "monthly value, constant within each month.",
        "",
        T(reg_sum),
        "",
        "Per calendar year (2026 is partial, up to the dataset end):",
        "",
        T(yearly),
        "",
        "Monthly means, last 16 months (the last month is partial). Read this before trusting "
        "the `post_crisis` label for the most recent folds:",
        "",
        T(recent),
        "",
        "![weekly price](weekly_price_regimes.png)",
        "",
        "## 2. Daily profiles",
        "",
        "Mean price by local hour. Shape descriptors (peak/trough hour, spread = peak − trough):",
        "",
        T(shape_season),
        "",
        T(shape_daytype),
        "",
        "![profiles by season](profiles_season.png)",
        "",
        "![profiles weekday/weekend](profiles_daytype.png)",
        "",
        "## 3. Negative prices",
        "",
        "Count of negative-price hours per year, local hour of day and month (all years):",
        "",
        T(neg_year.to_frame().T, floatfmt=".0f"),
        "",
        T(neg_hour.to_frame().T, floatfmt=".0f"),
        "",
        T(neg_month.to_frame().T, floatfmt=".0f"),
        "",
        "Conditional on the Elia day-ahead 11AM forecasts, post-crisis regime only "
        "(the 11AM run is available at the issue time; solar starts 2020-10):",
        "",
        "Solar forecast (MW):",
        "",
        T(neg_solar),
        "",
        "Wind forecast (MW):",
        "",
        T(neg_wind),
        "",
        "(Wind + solar forecast) / load forecast (%):",
        "",
        T(neg_res),
        "",
        "![negative heatmap](negative_heatmap_hour_month.png)",
        "",
        "## 4. Merit order: price vs residual load",
        "",
        "Residual load forecast = `load_forecast` − `elia_wind_dayahead11hforecast` − "
        "`elia_solar_dayahead11hforecast`. **Fallback**: where the Elia 11AM run is missing, the "
        "ENTSO-E `fc_*` series (Elia 6PM run) is used instead — "
        f"{fb_share:.1f}% of hours ({fb_text}; the Elia solar series starts 2020-10, the 2026 "
        "hours are short Elia gaps). This is fine for description, but `fc_*` are "
        "baseline-only and must never be model features (D-16 / D-29).",
        "",
        "OLS slope of the hourly price on the residual load (EUR/MWh per GW), per regime. "
        "`fc_fallback_hours` = hours whose residual load uses the `fc_*` 6PM-run fallback: the "
        "pre-crisis slope rests mostly on them.",
        "",
        T(mo_slope.reindex([r for r in eda.REGIME_ORDER if r in mo_slope.index]), floatfmt=".2f"),
        "",
        "Same slope by gas price level (`ttf_gas`: IMF monthly proxy to Sep 2021, THE VTP daily "
        "after, D-25; all years pooled; the dataset value is already the D-2 close, `commodities.publication_lag_days`). `gas_proxy_hours` = "
        "hours where the gas value is the monthly proxy:",
        "",
        T(mo_slope_gas.reindex([g for g in gas_labels if g in mo_slope_gas.index]),
          floatfmt=".2f"),
        "",
        "Binned median price per 1-GW residual-load bin (bins with < "
        f"{eda.MIN_BIN_COUNT} hours dropped):",
        "",
        T(mo_pivot),
        "",
        "![merit order per regime](merit_order_regimes.png)",
        "",
        "![merit order by gas level](merit_order_gas.png)",
        "",
        "## 5. Correlations with core drivers",
        "",
        "Same-hour correlations with `price_da`; candidate families (D-24: `nb_`, `unav_`, `xch_`, "
        "`fb_`, `cap_BE_`, `hydro_res_`, `wfr_`, `cmd_`, `flag_`, other `elia_` runs) excluded. "
        "`availability` says how the column may enter the model at the D-1 11:00 issue time — "
        "a same-hour correlation of a lag-only or baseline-only column is **not** usable "
        "information as such.",
        "",
        T(corr, floatfmt=".2f"),
        "",
        "Gas price vs `price_da` on **daily means**, excluding the monthly-proxy hours "
        "(i.e. THE VTP daily price, Oct 2021 onward) and hours without a price:",
        "",
        T(gas_corr, floatfmt=".2f"),
        "",
    ]
    (out / "eda_summary.md").write_text("\n".join(md), encoding="utf-8")
    logger.info("wrote %s", out / "eda_summary.md")


if __name__ == "__main__":
    main()
