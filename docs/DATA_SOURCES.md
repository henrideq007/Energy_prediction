# Data sources

All sources are free. Everything is downloaded by `python -m energy_forecast -v fetch` and cached in
`data/raw/<source>/` (git-ignored), then assembled into `data/processed/dataset.parquet`.

## Core sources (used by the model)

| # | Source | Data | Access | Columns |
|---|---|---|---|---|
| 1 | [ENTSO-E Transparency Platform](https://transparency.entsoe.eu) | Day-ahead prices (BE, FR, NL, DE-LU), BE actual load & load forecast, BE generation per type, BE wind/solar & total generation day-ahead forecasts | REST API via `entsoe-py`, free token in `.env` | `price_da*`, `load_*`, `gen_*`, `fc_*` |
| 2 | [Open-Meteo](https://open-meteo.com) | Temperature, 100 m wind speed, solar radiation, cloud cover — Brussels, Antwerp, Liège, offshore wind zone | REST, no key (ERA5 archive + live forecast) | `w_<point>_<var>` |
| 3 | Yahoo Finance `TTF=F` + local cache | Real TTF front-month closes; retried, every successful download cached in `data/raw/ttf_yahoo_cache.csv` (D-23). Yahoo only serves recent quotes since Nov 2026 → the cache builds the TTF record from now on. Wins over the sources below | `yfinance` | `ttf_gas` |
| 3b | Manual CSV `data/external/ttf_prices.csv` | Optional real TTF closes (`date,price`), fill days Yahoo/cache lack | file | `ttf_gas` |
| 3c | [THE — Trading Hub Europe](https://api.tradinghub.eu/api/dataexport/manual/en) | Official daily VTP average gas price, German hub, from 1 Oct 2021 (TTF substitute, D-25) | REST, no key | `ttf_gas` |
| 3d | [IMF via FRED](https://fred.stlouisfed.org/series/PNGASEUUSDM) | Monthly EU gas price (TTF-based) → EUR/MWh, back-fill 2019 → Sep 2021 only | CSV, no key | `ttf_gas`, `flag_gas_monthly_proxy` |
| 5 | [EEX EU ETS auctions](https://www.eex.com/en/markets/environmentals/eu-ets1-eu-ets2-auctions/eu-ets1-auctions) | EUA primary-auction clearing price (≈210 days/year), 2018 → 2025 | Yearly xlsx reports (archive zip auto-downloaded) | `eua_carbon` |
| 6 | Yahoo Finance `CO2.L` | SparkChange EUA ETC (EUR) × rolling auction/ETC ratio — fills auction-free days and 2026 (D-26) | `yfinance` | `eua_carbon`, `flag_eua_etc_proxy` |
| 7 | Python `holidays` | Belgian public holidays | package | features only |

## Candidate sources (collected, NOT used by `features.py` until an ablation test — D-15, D-24)

| Source | Data | Columns |
|---|---|---|
| ENTSO-E (FR, NL, DE-LU) | Load forecast & actual, wind/solar forecast, generation forecast, FR nuclear generation (DP-029..036) | `nb_<zone>_*` |
| ENTSO-E outages (A80) | Nuclear unit unavailability BE & FR **as known at the D-1 issue time (11:00, D-29)**, from the full revision history (D-27). BE only from 2022 (no earlier messages on ENTSO-E) | `unav_BE_nuclear_mw`, `unav_FR_nuclear_mw` |
| ENTSO-E exchanges | Day-ahead scheduled exchanges BE↔FR/NL/DE-LU/GB, BE net position (auction results → lag only) | `xch_*` |
| ENTSO-E capacity / hydro | BE installed capacity per type (yearly), FR & CH reservoir filling (weekly) | `cap_BE_*`, `hydro_res_*` |
| [JAO Core](https://publicationtool.jao.eu/core) (`jao-py`) | Flow-based BE min/max net position, from Jun 2022 (DP-040) | `fb_BE_min_np`, `fb_BE_max_np` |
| [Elia Open Data](https://opendata.elia.be) | Wind (ods031) & solar (ods032 + ods209) measured + week-ahead / day-ahead 11h / day-ahead runs (D-28) | `elia_<wind|solar>_*` |
| Open-Meteo | Temperature in 5 French cities (DP-043) | `wfr_<city>_temperature_2m` |
| Yahoo `MTF=F` | Rotterdam coal (DP-047) — Yahoo history stops Dec 2025 | `cmd_coal_api2` |
| [GIE AGSI+](https://agsi.gie.eu) | EU gas storage % full (DP-048) — **needs a free key** `AGSI_API_KEY` in `.env` | `cmd_gas_storage_eu_pct` |

Not usable: Open-Meteo ensemble (only ~3 months of history → live-only, DP-042); EEX futures, TTF
day-ahead, EPEX curves (paid, D-17).

## Getting the keys
- **ENTSO-E**: account on transparency.entsoe.eu → email transparency@entsoe.eu, subject "Restful API access"
  → *My Account Settings* → *Generate a new token* → `ENTSOE_API_KEY=...` in `.env`.
- **AGSI+ (optional)**: register at https://agsi.gie.eu → copy the API key → `AGSI_API_KEY=...` in `.env`.

## Manual files
- `data/external/ttf_prices.csv` (`date,price`): fills gas days that Yahoo / its cache do not have (wins over THE and IMF).
- `data/external/eua_prices.csv` (`date,price`): optional override, wins over the automatic carbon sources. ISO or day-first dates and decimal commas are accepted.
- `data/raw/eex/`: drop the current-year *Emission Spot Primary Market Auction Report* xlsx here to replace the
  ETC proxy (not linked statically on eex.com, so it cannot be downloaded automatically).

## Publication-time check (decision D-16)
Run `python scripts/check_publication_times.py` at 09:00, 09:45, 10:15, 12:00 and 18:30 on a few days.
Each run appends to `reports/publication_times.csv` whether tomorrow's forecasts are already published.
Only series available before the 11:00 issue time (D-29) may be used as same-time features.

## Known data quirks
- Pumped storage (and sometimes offshore wind) is left EMPTY by ENTSO-E when it does not generate → treated as 0.
- BE nuclear = 0 MW from April to October 2026 (Doel 4 / Tihange 3 outage) — a regime the model must handle.
- `fc_gen_total` (A71) is on average ~440 MW below actual total generation: a weak baseline for `gen_total`.
- Gas before Oct 2021 is a MONTHLY step (published the month after) → it lags fast moves such as the Sep 2021 surge.
- Elia solar history starts Oct 2020; JAO flow-based starts Jun 2022; EUA ETC starts Oct 2021.
