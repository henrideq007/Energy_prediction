# Data sources

| # | Source | Data | Access | Cost | Status |
|---|---|---|---|---|---|
| 1 | [ENTSO-E Transparency Platform](https://transparency.entsoe.eu) | Day-ahead prices (BE, FR, NL, DE-LU), actual load, load forecast, actual generation per type, wind & solar day-ahead forecasts, total generation forecast | REST API via `entsoe-py`, needs a free token | Free | Implemented (primary) |
| 2 | [Open-Meteo](https://open-meteo.com) | Temperature, wind speed, solar radiation, cloud cover for Brussels, Antwerp, Liège, offshore wind zone | REST, no key (archive, historical-forecast, live forecast APIs) | Free (non-commercial) | Implemented |
| 3 | Yahoo Finance (`yfinance`) + CSV fallback | TTF natural gas front-month (`TTF=F`); fallback `data/external/ttf_prices.csv` (`date,price` in EUR/MWh) | Python package / manual CSV | Free, unofficial | Yahoo returned **no data** on 3 Nov 2026 → use the CSV fallback |
| 4 | Manual CSV | EUA carbon price (`data/external/eua_prices.csv`, columns `date,price`) | e.g. export from a market data site | Free | Optional |
| 5 | [Elia Open Data](https://opendata.elia.be) | Belgian load, solar/wind estimates & forecasts at 15-min, imbalance prices | Opendatasoft API v2.1 | Free | Optional (disabled) |

## Getting the ENTSO-E token
1. Create an account on https://transparency.entsoe.eu.
2. Send an email to **transparency@entsoe.eu** with subject **"Restful API access"** and your account email in the body.
3. Once approved (usually a few days), go to *My Account Settings* → *Generate a new token*.
4. Copy `.env.example` to `.env` and paste it: `ENTSOE_API_KEY=...`.

## Manual CSVs (data/external/, git-ignored — never committed)
- `ttf_prices.csv` and `eua_prices.csv`: two columns `date,price`, one row per trading day. ISO dates (`2026-10-27`)
  or day-first dates (`27/10/2026`) and decimal commas are accepted. If Yahoo works again, the CSV only fills gaps.
- Check the terms of the site you export from; the files stay local because `data/external/*` is git-ignored.

## Publication-time check (decision D-16)
Run `python scripts/check_publication_times.py` at 09:00, 09:45, 10:15, 12:00 and 18:30 on a few days.
Each run appends to `reports/publication_times.csv` whether tomorrow's load, wind/solar and generation
forecasts (BE, FR, NL, DE-LU) are already published. Only series available before 10:00 may be used as
same-time features.

## Known data quirks (first real fetch, 3 Nov 2026)
- Pumped storage (and sometimes offshore wind) is left EMPTY by ENTSO-E when it does not generate → treated as 0.
- BE nuclear = 0 MW from April to October 2026 (outage of the remaining units) — a regime the model must handle.
- `fc_gen_total` (A71) is on average ~440 MW below actual total generation: a weak baseline for `gen_total`.

## Ideas for later (backlog)
- Cross-border scheduled flows / net transfer capacity (ENTSO-E)
- Nuclear unit unavailability (ENTSO-E "unavailability of generation units") — big driver in BE
- Historical weather *forecasts* instead of reanalysis
- Elia imbalance prices → extension to balancing-market forecasting
