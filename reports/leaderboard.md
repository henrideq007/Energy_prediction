# Backtest leaderboard — run `20261122-1954-8772` (data: real)

Walk-forward, expanding window, monthly folds. Lower MAE/RMSE/rMAE is better; rMAE < 1 means the model beats the weekly seasonal-naive baseline.

## gen_solar

| model | MAE | RMSE | rMAE | sMAPE % | DirAcc | PeakHit |
|---|---|---|---|---|---|---|
| tso_forecast | 167.92 | 353.27 | 0.277 | 18.5 | 0.939 | 0.921 |
| lightgbm | 175.45 | 381.84 | 0.289 | 71.0 | 0.909 | 0.890 |
| xgboost | 177.05 | 384.11 | 0.292 | 69.3 | 0.914 | 0.893 |
| ridge | 221.61 | 420.75 | 0.365 | 71.2 | 0.903 | 0.882 |
| naive_day | 492.93 | 1039.25 | 0.812 | 32.2 | 0.900 | 0.715 |
| seasonal_naive_week | 606.72 | 1251.17 | 1.000 | 38.2 | 0.886 | 0.688 |

## gen_total

| model | MAE | RMSE | rMAE | sMAPE % | DirAcc | PeakHit |
|---|---|---|---|---|---|---|
| tso_forecast | 565.97 | 839.55 | 0.435 | 8.8 | 0.796 | 0.641 |
| ridge | 716.11 | 905.58 | 0.551 | 11.3 | 0.794 | 0.721 |
| lightgbm | 750.58 | 960.60 | 0.577 | 11.8 | 0.781 | 0.712 |
| xgboost | 766.32 | 979.84 | 0.589 | 12.1 | 0.777 | 0.707 |
| seasonal_naive_week | 1300.82 | 1697.37 | 1.000 | 19.8 | 0.701 | 0.471 |
| naive_day | 1307.63 | 1647.51 | 1.005 | 20.2 | 0.711 | 0.545 |

## gen_wind

| model | MAE | RMSE | rMAE | sMAPE % | DirAcc | PeakHit |
|---|---|---|---|---|---|---|
| lightgbm | 207.02 | 286.83 | 0.153 | 22.9 | 0.710 | 0.666 |
| xgboost | 210.06 | 286.21 | 0.156 | 24.1 | 0.710 | 0.677 |
| tso_forecast | 243.58 | 340.10 | 0.180 | 26.6 | 0.743 | 0.710 |
| ridge | 254.02 | 332.54 | 0.188 | 33.0 | 0.705 | 0.647 |
| naive_day | 1258.80 | 1646.41 | 0.932 | 90.3 | 0.535 | 0.184 |
| seasonal_naive_week | 1350.62 | 1745.73 | 1.000 | 94.5 | 0.511 | 0.159 |

## price_da

| model | MAE | RMSE | rMAE | sMAPE % | DirAcc | PeakHit |
|---|---|---|---|---|---|---|
| xgboost | 17.99 | 29.06 | 0.493 | 28.2 | 0.832 | 0.819 |
| lightgbm | 18.13 | 29.08 | 0.496 | 28.1 | 0.835 | 0.797 |
| random_forest | 19.06 | 30.80 | 0.522 | 29.4 | 0.843 | 0.797 |
| ridge | 20.66 | 32.36 | 0.566 | 31.9 | 0.844 | 0.811 |
| naive_day | 28.87 | 46.65 | 0.791 | 40.7 | 0.802 | 0.641 |
| seasonal_naive_week | 36.51 | 57.60 | 1.000 | 47.7 | 0.805 | 0.644 |
