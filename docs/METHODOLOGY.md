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

### Candidate features & publication lags (T45)

The Phase 1 candidate columns (D-24) are **not** in the default feature matrix. `features.candidate_features()`
builds them on request — `build_features(..., candidate_families=[...])` or
`energy-forecast backtest --candidates xch nb_actual ...` — with the lags of `config.yaml > candidate_features`.
For delivery hour t on day D the issue time D-1 11:00 lies 13 h (t = D 00:00) to 36 h (t = D 23:00; 37 h on
a 25-h day) before t. A lag h means the feature at t is the source value at t−h (column `<col>_lag<h>`);
lag 0 keeps `<col>`. `features.CANDIDATE_MIN_LAG_H` is a hard floor, independent of the config: a shorter
lag raises an error and `leakage_check()` flags any candidate column without its lag. Lagged candidate
values whose source hour t−h is not on a local date strictly before the delivery day are set to NaN (DST,
see below). Neighbour, Elia week-ahead, AGSI and JAO
publication times are not verified yet (T53), hence the conservative choices. Status of every family:
**candidate — awaiting ablation (D-15)**.

| Family | Columns | Lags (h) | Rationale |
|---|---|---|---|
| `xch` | `xch_*` (DA scheduled exchanges, BE net position) | 48, 168 | may include intraday renominations → treated like actuals (D-05) |
| `nb_actual` | `nb_*_load_actual`, `nb_FR_gen_nuclear` | 48, 168 | same rule as BE actuals (D-05) |
| `nb_fc` | `nb_*_load_fc`, `nb_*_fc_*` | 24, 168 | forecast for D-1 is out by ~18:00 D-2; same-time only once T53 verifies publication < 11:00 |
| `fb` | `fb_BE_min_np`, `fb_BE_max_np` (JAO, from Jun 2022) | 24, 168 | same-time pending T53 |
| `unav` | `unav_*_nuclear_mw` + `nuc_BE_gap_proxy_lag48` | 0 (proxy: 48) | already rebuilt as known at the issue time (D-27). BE masked to NaN before 2022-01-01 (see below) |
| `cap` | `cap_BE_*` | 0 | yearly installed capacity, published before the year. Yearly values can be revised after the fact on ENTSO-E (the stored value is the latest, not necessarily the one known then) |
| `hydro_res` | `hydro_res_FR_mwh`, `hydro_res_CH_mwh` | 336 | weekly, see below |
| `wfr` | `wfr_<city>_temperature_2m` | 0 | weather, same treatment as `w_*` (same ERA5 optimism) |
| `elia_other` | `elia_*_weekaheadforecast` / `elia_*_dayaheadforecast` / `elia_*_measured` | 24 / 24 / 48, 168 | week-ahead: publication time unverified (D-16) → same-time pending T53/verification; latest DA run published after 11:00; measured = actuals |
| `cmd` | `cmd_coal_api2` / `cmd_gas_storage_eu_pct` (AGSI, only with `AGSI_API_KEY`) | 0 / 48 | coal: closes already shifted by `commodities.publication_lag_days` (D-2 close), history ends Jan 2026. AGSI: gas day X is published ~18:00 CET on X+1 and revised later, but stamped X+2 00:00 UTC → lag 0 would use D-2 (published after the issue time) → lag 48 (floor 48) |
| — | `flag_*` | never | data-quality flags, never a feature |

**Hydro reservoirs.** The weekly value of week W is forward-filled from its stamp. Observed stamps
(Brussels time): FR Monday 01:00 ×210, Monday 00:00 ×175, Sunday 23:00 ×19; CH Monday 01:00 ×243,
Monday 00:00 ×164 — i.e. mostly Sunday 23:00 UTC; the earliest is Sunday 23:00 local, 1 h before Monday
00:00. Assumption: published at the latest at the end of the Thursday after W ends (Monday 00:00 of W +
264 h). Worst case, the first row using a value is the last hour of its day (issue = t − 37 h), so
h ≥ 264 + 1 + 37 = **302 h** (`features.hydro_min_safe_lag_h`), valid for any stamp from Sunday 23:00 on.
Simulated hour by hour over 2024–2025 with stamps at Sunday 23:00 / Monday 00:00 / Monday 01:00, the exact
minimum is 290 h. We use **336 h** (14 days).

**BE nuclear unavailability.** ENTSO-E has no BE outage messages before 2022, so `unav_BE_nuclear_mw` is
exactly 0 for every hour of 2019–2021: 0 means "unknown", not "no outage". It is set to NaN before
2022-01-01 (`valid_from`; first non-zero value: 2022-01-27; January 2022 zeros are consistent with
capacity − generation ≈ 0). Caveat: the series still looks under-recorded in H1 2022 (e.g.
Feb–Mar 2022: capacity − generation ≈ 1 GW while `unav_BE` ≈ 0; quarterly correlation 0.14 in Q1 2022 vs
0.8–0.98 in most later quarters), possibly outages announced before the first stored message — to be
checked on the raw messages (data side). `nuc_BE_gap_proxy_lag48 = cap_BE_nuclear − gen_nuclear(t−48 h)` covers the full
history; it also absorbs modulation and closures within a year (capacity is yearly).

**DST note.** Lags are row shifts on the UTC grid. On the 25-h autumn day, 23:00 − 24 h is 00:00 of the
same day D, which is not known at the D-1 issue time. For candidate features this is **handled by masking**:
`candidate_features()` sets a lagged value to NaN whenever the local date of t − h is not strictly before
the delivery date of t (1 row per year for 24 h lags, none for 48/168/336 h; tested hour by hour over 2025).
The default feature `price_da_lag24` is still affected (1 h/year) — follow-up, not changed here.

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
