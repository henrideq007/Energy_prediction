# Data sources

| # | Source | Data | Access | Cost | Status |
|---|---|---|---|---|---|
| 1 | [ENTSO-E Transparency Platform](https://transparency.entsoe.eu) | Day-ahead prices (BE, FR, NL, DE-LU), actual load, load forecast, actual generation per type, wind & solar day-ahead forecasts, total generation forecast | REST API via `entsoe-py`, needs a free token | Free | Implemented (primary) |
| 2 | [Open-Meteo](https://open-meteo.com) | Temperature, wind speed, solar radiation, cloud cover for Brussels, Antwerp, Liège, offshore wind zone | REST, no key (archive, historical-forecast, live forecast APIs) | Free (non-commercial) | Implemented |
| 3 | Yahoo Finance (`yfinance`) | TTF natural gas front-month (`TTF=F`) | Python package | Free, unofficial | Implemented |
| 4 | Manual CSV | EUA carbon price (`data/external/eua_prices.csv`, columns `date,price`) | e.g. export from a market data site | Free | Optional |
| 5 | [Elia Open Data](https://opendata.elia.be) | Belgian load, solar/wind estimates & forecasts at 15-min, imbalance prices | Opendatasoft API v2.1 | Free | Optional (disabled) |

## Getting the ENTSO-E token
1. Create an account on https://transparency.entsoe.eu.
2. Send an email to **transparency@entsoe.eu** with subject **"Restful API access"** and your account email in the body.
3. Once approved (usually a few days), go to *My Account Settings* → *Generate a new token*.
4. Copy `.env.example` to `.env` and paste it: `ENTSOE_API_KEY=...`.

## Ideas for later (backlog)
- Cross-border scheduled flows / net transfer capacity (ENTSO-E)
- Nuclear unit unavailability (ENTSO-E "unavailability of generation units") — big driver in BE
- Historical weather *forecasts* instead of reanalysis
- Elia imbalance prices → extension to balancing-market forecasting
