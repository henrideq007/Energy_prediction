# Backtest leaderboard — run `20261102-2047-7526` (data: synthetic)

Walk-forward, expanding window, monthly folds. Lower MAE/RMSE/rMAE is better; rMAE < 1 means the model beats the weekly seasonal-naive baseline.

## gen_solar

| model | MAE | RMSE | rMAE | sMAPE % | DirAcc | PeakHit |
|---|---|---|---|---|---|---|
| lightgbm | 25.37 | 41.58 | 0.041 | 28.6 | 0.989 | 0.989 |
| ridge | 35.30 | 45.14 | 0.056 | 54.9 | 0.926 | 0.978 |
| tso_forecast | 205.38 | 372.84 | 0.329 | 7.8 | 0.923 | 0.772 |
| naive_day | 591.91 | 1009.06 | 0.947 | 65.2 | 0.606 | 0.543 |
| seasonal_naive_week | 624.85 | 1060.66 | 1.000 | 66.9 | 0.587 | 0.554 |

## gen_total

| model | MAE | RMSE | rMAE | sMAPE % | DirAcc | PeakHit |
|---|---|---|---|---|---|---|
| lightgbm | 133.87 | 170.32 | 0.401 | 1.3 | 0.839 | 0.837 |
| ridge | 138.07 | 172.36 | 0.414 | 1.3 | 0.854 | 0.870 |
| tso_forecast | 238.96 | 303.28 | 0.717 | 2.3 | 0.758 | 0.707 |
| seasonal_naive_week | 333.47 | 434.46 | 1.000 | 3.2 | 0.569 | 0.565 |
| naive_day | 560.57 | 683.05 | 1.681 | 5.5 | 0.568 | 0.522 |

## gen_wind

| model | MAE | RMSE | rMAE | sMAPE % | DirAcc | PeakHit |
|---|---|---|---|---|---|---|
| lightgbm | 71.70 | 98.45 | 0.113 | 19.4 | 0.923 | 0.793 |
| ridge | 98.21 | 125.47 | 0.155 | 30.2 | 0.863 | 0.750 |
| tso_forecast | 116.43 | 177.07 | 0.183 | 13.8 | 0.887 | 0.685 |
| naive_day | 584.20 | 741.15 | 0.921 | 87.0 | 0.502 | 0.130 |
| seasonal_naive_week | 634.50 | 795.21 | 1.000 | 91.0 | 0.488 | 0.174 |

## price_da

| model | MAE | RMSE | rMAE | sMAPE % | DirAcc | PeakHit |
|---|---|---|---|---|---|---|
| lightgbm | 9.43 | 13.04 | 0.418 | 15.0 | 0.712 | 0.391 |
| ridge | 14.86 | 20.47 | 0.658 | 23.2 | 0.695 | 0.326 |
| naive_day | 21.40 | 36.88 | 0.947 | 27.9 | 0.530 | 0.239 |
| seasonal_naive_week | 22.59 | 39.31 | 1.000 | 30.0 | 0.527 | 0.272 |
