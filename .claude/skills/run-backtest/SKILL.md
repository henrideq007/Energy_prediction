---
name: run-backtest
description: Run a reproducible walk-forward backtest (or ablation) on the real Belgian dataset and report results in the project format. Use when a task asks to compare models, test a feature/driver family, or refresh the leaderboard.
---

# run-backtest

## 1. Data
```bash
python scripts/publish_data.py restore
python -m energy_forecast validate
```
If the release is missing → stop and report "no real data available"; do **not** fall back to
synthetic numbers for results.

## 2. Run
- Full (for claims): `python -m energy_forecast -v backtest`
- Quick iteration: `python -m energy_forecast -v backtest --targets price_da --models naive_day seasonal_naive_week lightgbm --folds 3`
- Outputs: `reports/leaderboard.md`, `reports/leaderboard.csv`, `reports/backtest_fold_metrics.csv`,
  plots `reports/backtest_<target>.png`.

## 3. Ablation (driver family X)
1. Baseline run with the current feature set → save `reports/leaderboard.csv` as `before.csv`.
2. Run with family X added (or removed) — same folds, same models, same `random_state`.
3. Compare per fold: ΔMAE = after − before. Keep X only if mean ΔMAE < 0 **and** it improves
   in a majority of folds (D-15).

## 4. Report
| target | model | MAE | rMAE | DirAcc | PeakHit | MAE fold min–max |
|---|---|---|---|---|---|---|

Always include `naive_day` and `seasonal_naive_week` rows. State: data period, weather
source (`archive` = ERA5, optimistic), exact command, commit SHA. Provide the Notion
Experiments & Results row (hypothesis · setup · result · conclusion).
Commit only `reports/*.md`, `reports/*.csv` and plots — never parquet files.
