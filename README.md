# ⚡ Belgian Electricity Price & Production Forecasting

End-to-end machine-learning project that forecasts the **next 24 hours** of the Belgian day-ahead electricity **price** and **production** (total, solar, wind), using grid data (ENTSO-E), weather (Open-Meteo) and fuel/carbon prices.

> Forecast issued on **D-1 at 10:00 (Brussels)**, before the 12:00 day-ahead auction, for the 24 delivery hours of day **D**.

```
ENTSO-E ─┐                    ┌─ naive / seasonal naive / TSO forecast (baselines)
Weather ─┼─> clean & validate ─> features ─> walk-forward backtest ─┼─ Ridge, Random Forest
TTF/EUA ─┘   (no leakage)                                         └─ LightGBM, XGBoost (+ quantiles)
                                                         │
                                         best model per target ─> live forecast ─> CLI / FastAPI
```

## Project status
Tracked in Notion (business plan, roadmap, decision log, experiments). Repo docs: [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md) · [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) · [`docs/DECISIONS.md`](docs/DECISIONS.md)

| Phase | Content | Status |
|---|---|---|
| 0 | Scope, plan, repo, tracker | ✅ |
| 1 | Data collection (ENTSO-E, weather, commodities) | 🟡 code ready — needs API token + first fetch |
| 2 | Cleaning, validation, EDA | 🟡 code ready |
| 3 | Features & train/test split | 🟡 code ready |
| 4 | Model comparison (walk-forward backtest) | 🟡 code ready — tested on synthetic data |
| 5 | Live forecasting (API) | 🟡 code ready |
| 6 | Dashboard, monitoring, write-up (LinkedIn) | ⬜ |

## Quick start (Windows, VS Code)

```powershell
# 1. Get the code into your project folder
cd "C:\Users\henri\OneDrive\Documents\05_Project"
git clone https://github.com/henrideq007/energy-price-prediction.git Energy_prediction
cd Energy_prediction
#    (if the folder already exists and is not empty:
#     git init; git remote add origin https://github.com/henrideq007/energy-price-prediction.git; git pull origin main)

# 2. Virtual environment (Python 3.11 or 3.12)
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1        # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt

# 3. Check everything works without any API key (synthetic data)
pytest
python -m energy_forecast demo

# 4. Real data
copy .env.example .env             # then paste your ENTSO-E token in .env
python -m energy_forecast -v fetch
python -m energy_forecast validate
python -m energy_forecast -v backtest
python -m energy_forecast train
python -m energy_forecast explain
python -m energy_forecast predict  # tomorrow's 24h forecast -> forecasts/

# 5. API
uvicorn api.app:app --reload       # http://127.0.0.1:8000/docs
```

Tip: the folder is inside OneDrive — the `.venv` folder contains thousands of files. Either pause OneDrive sync while installing, or mark `.venv` as "free up space"/excluded. Data and models are git-ignored (they are regenerable).

VS Code: open the folder, accept the recommended extensions, select the `.venv` interpreter. `Run and Debug` has ready-made launch configs (Demo, Fetch, Backtest, Predict, API). `notebooks/01_eda.py` runs cell by cell (`# %%`).

## Repository layout

```
config/config.yaml          every tunable parameter (market, dates, features, models)
src/energy_forecast/
  data/                     entsoe_source, weather, commodities, elia, synthetic, build_dataset
  validation.py             cleaning + validation report
  features.py               feature engineering with anti-leakage rules
  split.py                  train/val/test + walk-forward folds
  models/registry.py        model zoo (baselines -> GBMs)
  metrics.py                MAE, RMSE, sMAPE, rMAE, direction accuracy, peak-hour hit
  backtest.py · train.py · predict.py · explain.py · cli.py
api/app.py                  FastAPI service (/health, /models, /forecast)
notebooks/01_eda.py         exploratory analysis
tests/                      unit tests (run in GitHub Actions CI)
docs/                       methodology, data sources, decision log
data/ models/ reports/ forecasts/   generated outputs (git-ignored)
```

## Results
Run `python -m energy_forecast backtest` → `reports/leaderboard.md`. Real-data results will be added here and in Notion once the first fetch is done. (The `demo` command uses synthetic data — its numbers are not market results.)

## License
MIT
