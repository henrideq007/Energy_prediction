# Methodology

## 1. Problem definition

| Item | Choice |
|---|---|
| Market | Belgian bidding zone (BE), Single Day-Ahead Coupling (SDAC) |
| Targets | `price_da` (EUR/MWh) · `gen_total`, `gen_solar`, `gen_wind` (MW) |
| Horizon | 24 delivery hours of day **D** |
| Issue time | **D-1 at 11:00 Europe/Brussels** (before the 12:00 SDAC gate closure; D-29, was 10:00 in D-02) |
| Resolution | Hourly. Since 1 Oct 2025 SDAC clears 15-min products; we average to hourly for one consistent history. |

Why this setup: it is the decision a real market participant faces — "what bid do I submit for tomorrow before noon?" — and it forces honest features.

## 2. Information available at issue time (anti-leakage rules)

| Information | Known at D-1 11:00? | How it is used |
|---|---|---|
| Day-ahead prices up to D-1 (BE + FR/NL/DE-LU) | Yes (auction on D-2) | lags ≥ 24h, D-1 daily stats |
| Actual load / generation | Only up to ~D-1 10:00 | lags ≥ **48h** |
| TSO day-ahead load forecast for D (ENTSO-E A65) | Yes (due 2 h before gate closure) | same-time feature |
| Elia wind/solar "day-ahead 11AM" run for D | Yes (published 11:00) | same-time features (D-29) |
| ENTSO-E A69/A71 wind/solar/total-gen forecasts (`fc_*`) | **No** — it is Elia's 6PM run (D-29) | `tso_forecast` baseline only, never a feature |
| Weather forecast for D | Yes | same-time features (backtest proxy: see §4) |
| TTF gas / EUA carbon closes | Up to D-2 | shifted by 2 days |

`features.leakage_check()` and the unit tests enforce these rules on every run.

## 3. Pipeline

1. **Collect** — `energy-forecast fetch` → ENTSO-E (prices, load, generation, TSO forecasts), Open-Meteo (weather), Yahoo Finance (TTF), optional EUA CSV.
2. **Clean & validate** — `energy-forecast validate`:
   - continuous UTC hourly grid (avoids DST bugs), duplicates dropped
   - physically impossible values → NaN (price outside SDAC limits, negative load…)
   - gaps ≤ 3h interpolated, longer gaps left as NaN
   - price spikes & negative prices are **flagged, never removed** (they are real and are what we want to predict)
3. **Features** — calendar & Belgian holidays, price lags, actuals lags, D-1 price stats, rolling means, TSO forecasts, weather, residual load forecast, CCGT short-run marginal cost (gas/0.5 + 0.37 × CO2).
4. **Split** — chronological only. Walk-forward backtest: expanding training window, one month of test per fold, model refit each fold.
5. **Models** — baselines first, then linear, then tree ensembles (see `models/registry.py`).
6. **Evaluate** — MAE (primary), RMSE, sMAPE, rMAE vs weekly naive, direction accuracy (hour-to-hour price moves), peak-hour hit rate.
7. **Explain** — SHAP values of LightGBM: which drivers move the price.
8. **Deploy** — train on all history, predict tomorrow with live data, serve via FastAPI.

**EDA (T11).** `python scripts/run_eda.py` runs the descriptive analysis in `src/energy_forecast/eda.py`
on `dataset_clean.parquet` (in Europe/Brussels local time) and writes `reports/eda/eda_summary.md`
plus figures in `reports/eda/`: price regimes (pre-crisis 2019 → Jun 2021, crisis Jul 2021 → Jun 2023,
post-crisis Jul 2023 →; fixed calendar cut points, not estimated change points), hourly profiles by
season and weekday/weekend, negative prices (per year, hour × month, conditional on the Elia 11AM
wind/solar forecasts), the merit order (price vs residual load forecast = `load_forecast` − Elia
11AM wind and solar, with a flagged `fc_*` fallback before Oct 2020) and same-hour correlations with
the core drivers. Gas statistics use `ttf_gas`, which is not TTF for most of the history (IMF monthly proxy to Sep 2021, THE VTP daily after, D-25); gas–price correlations are reported on daily means from Oct 2021 only. The report opens with the key insights. It is descriptive only: the `fc_*` series it
mentions remain baseline-only (D-16/D-29), and any driver it suggests still needs an ablation (D-15).
`notebooks/01_eda.py` uses the same functions interactively.

## 4. Known limitations / honesty notes

- **Weather in backtests**: the ERA5 archive is *observed* weather, better than any real forecast → backtest slightly optimistic. Switch `weather.source: historical_forecast` (archived forecasts, ~2022+) for a realistic run.
- **Regime changes**: the 2021-2023 energy crisis and the Belgian nuclear phase-down (several reactors closed 2022-2025; Doel 4 & Tihange 3 extended) change price dynamics. Consider training from 2023+ or adding regime features.
- **15-min MTU**: since Oct 2025, intra-hour price shape is lost by hourly averaging. Possible extension: predict 96 quarter-hours.
- **EUA carbon**: no free API → manual CSV for now.

## 5. Model selection rule

A model is promoted to production only if, on the walk-forward backtest:
1. its rMAE < 1 (beats weekly naive) **and** it beats `naive_day`;
2. for production targets, it beats `tso_forecast` (otherwise just use the TSO forecast);
3. its error is stable across months (check `backtest_fold_metrics.csv`).
