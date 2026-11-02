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
