# Decision log

Mirrors the Notion "Decision Log" database. Add a line for every choice that changes results.

| ID | Date | Decision | Why | Alternatives considered |
|---|---|---|---|---|
| D-01 | 2026-11-02 | Target market = Belgium (BE zone) | Differentiates from the many Spain/Germany GitHub projects; local relevance; rich ENTSO-E + Elia data | DE-LU, FR |
| D-02 | 2026-11-02 | Forecast = 24 hourly values of D, issued D-1 10:00 | Mirrors the real day-ahead bidding decision; makes leakage rules explicit | Rolling 24h-ahead from "now" |
| D-03 | 2026-11-02 | Hourly resolution (15-min prices averaged) | One consistent grain over 2019-2026; SDAC moved to 15-min only on 1 Oct 2025 | Predict 96 quarter-hours |
| D-04 | 2026-11-02 | ENTSO-E as primary source, Elia optional | One API covers BE + neighbours, consistent definitions | Elia only |
| D-05 | 2026-11-02 | Actual load/generation lags ≥ 48h; price lags ≥ 24h | Information availability at issue time | Using lag 24 for everything (leakage) |
| D-06 | 2026-11-02 | Flag but keep price spikes & negative prices | They are real market outcomes and must be predicted | Winsorising / removing outliers |
| D-07 | 2026-11-02 | Walk-forward monthly backtest, expanding window, refit each fold | Realistic, no look-ahead, shows stability over time | Single random split (invalid for time series) |
| D-08 | 2026-11-02 | One global model across hours (hour as a feature) | Simpler, more data per model; good with GBMs | 24 hour-specific models (LEAR style) → to test |
| D-09 | 2026-11-02 | Model zoo: naive, seasonal naive, TSO forecast, Ridge, RF, LightGBM, XGBoost | Baselines first, then increasing complexity | Deep learning (LSTM/TFT) → later phase |
| D-10 | 2026-11-02 | Primary metric MAE (EUR/MWh) + rMAE vs weekly naive; movement metrics DirAcc & PeakHit | MAE robust to spikes and interpretable; movement metrics match the "price movement" goal | MAPE (breaks near 0 € / negative prices) |
| D-11 | 2026-11-02 | Weather backtest proxy = ERA5 archive (flagged optimistic) | Full history since 2019; switch to historical-forecast API for a realistic run | Historical forecasts only (shorter history) |
| D-12 | 2026-11-02 | Serving: CLI + FastAPI + optional GitHub Actions daily job | Runs locally in VS Code, easy to deploy later (e.g. on a VPS) | Streamlit app first |
| D-13 | 2026-11-02 | Public GitHub repo, English documentation | Portfolio visibility; secrets kept in the git-ignored .env | Private repo; French docs |
| D-14 | 2026-11-02 | Data Point Inventory: Excel workbook = 49-column reference, Notion tracker = working status | Depth of documentation vs day-to-day tracking | Notion only; Excel only |
| D-15 | 2026-11-02 | Literature-driven data points (DP-029..DP-048) are candidates, kept only if they improve the walk-forward backtest | Evidence first (ablation by driver family) | Add everything; ignore literature |
| D-16 | 2026-11-02 | Verify the publication time of every D-1 forecast before using it as a same-time feature (`scripts/check_publication_times.py`) | Reg. 543/2013 art. 14: wind/solar & generation forecasts due by 18:00 D-1, after our 10:00 issue time | Assume all TSO forecasts are known at 10:00 |
| D-17 | 2026-11-02 | No paid data in v1 (EEX futures, TTF day-ahead, EPEX curves) | Licences incompatible with a public repo | Buy a data licence |
| D-18 | 2026-11-02 | Raise priority of nuclear availability features (BE + FR) | 2026 BE nuclear outage (0 MW Apr-Oct 2026 in the data); FR nuclear a top driver in the literature | Lagged nuclear generation only |
| D-19 | 2026-11-02 | Roadmap reorganised by phase in Notion | Plan, strategy and tasks per phase in one place | One big task database |
| D-20 | 2026-11-03 | Data fixes after the first real fetch: pumped storage / offshore wind "missing" = 0 MW; run-of-river typo fixed; interpolation limited to gaps <= 3 h (whole gap) | gen_hydro was 54% missing and partially interpolated; long gaps were partly filled by pandas `limit` | Drop gen_hydro |
| D-21 | 2026-11-03 | Backtest window = last 12 months (Nov 2025 -> Oct 2026) | Covers the 15-min MTU era and the 2026 nuclear outage, the regime the live model faces | Calendar year 2025 |
| D-22 | 2026-11-03 | Weather wind variable = wind_speed_100m (turbine hub height) | Closer to wind-power physics than 10 m | Keep 10 m |
