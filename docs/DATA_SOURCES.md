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

Opt-in only: `features.candidate_features` (T45) adds them, per family, with the publication lags of
`config.yaml > candidate_features` (e.g. `xch_*` and `nb_*_load_actual` lag ≥ 48 h, `nb_*` forecasts and `fb_*`
lag ≥ 24 h, Elia week-ahead run lag 24 h until its publication time is verified, AGSI gas storage lag 48 h,
`hydro_res_*` lag 336 h, `unav_BE_nuclear_mw` NaN before 2022). `cap_BE_*` yearly values can be revised
after the fact. Policy table:
`docs/METHODOLOGY.md` § "Candidate features & publication lags (T45)".

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
The GitHub workflow `publication-times.yml` runs `python scripts/check_publication_times.py` (no
arguments = every source, zones BE FR NL DE_LU) around 09:45, 10:15, 10:50, 11:05, 11:15, 12:00 and
18:30 Brussels. Each run appends one row per series to `reports/publication_times.csv` (kept in the
GitHub release `pubtimes`; columns `checked_at_local, delivery_day, zone, series, status, n_points`;
status `available | not_published | empty | error: <Exception>`). Logic: `src/energy_forecast/pubtimes.py`.
Only series available before the 11:00 issue time (D-29) may be used as same-time features.

| Series (`series` column) | Zone | Delivery day checked | Source |
|---|---|---|---|
| `load_forecast (A65)`, `wind_solar_forecast (A69)`, `generation_forecast (A71)`, `day_ahead_prices (A44)` | BE FR NL DE_LU | D+1 | ENTSO-E (needs `ENTSOE_API_KEY`) |
| `elia_wind_dayahead11h (ods086)`, `elia_solar_dayahead11h (ods087)` | BE | D+1 | Elia near-real-time datasets, field `dayahead11hforecast` (DP-027/028) |
| `elia_wind_dayahead (ods086)`, `elia_solar_dayahead (ods087)` | BE | D+1 | same datasets, field `dayaheadforecast` (latest run, for comparison) |
| `the_vtp_daily_price` | DE_THE | gas days today-1 and today | THE daily VTP average price (gas, D-25) |
| `jao_core_minmax_np` | BE | D+1 | JAO Core final flow-based domain, non-null `minBE` MTUs (DP-040) |

- Elia counts are the number of 15-min timestamps of D+1 (Brussels) with a non-null value, grouped by
  `datetime` so several region rows per timestamp count once.
- **Dataset-ID caveat:** the historical Elia datasets (ods031/ods032/ods209) lag ~2 days, so the check
  uses the near-real-time datasets `ods086` (wind) and `ods087` (solar). These IDs could not be verified
  from the cloud sandbox and are to be confirmed by the first CI run: a wrong ID shows up as
  `error: HTTPError` rows (constants `ELIA_WIND_NRT_DATASET` / `ELIA_SOLAR_NRT_DATASET` in `pubtimes.py`).
- A source that fails (network, missing key, missing package) gets `error: ...` rows; the other sources
  still run. `--sources entsoe elia the jao` and `--zones` restrict a manual run.

Analysis: `python scripts/check_publication_times.py --summarise [PATH]` (default
`reports/publication_times.csv`; download the log with `gh release download pubtimes -p publication_times.csv -D reports`)
prints per (zone, series) the earliest time of day it was `available`, the latest time it was still
not published, the number of delivery days covered and a verdict vs the cut-off
(`forecast.issue_hour_local`): `before cut-off` (available at a check before 11:00 on every day with a
pre-cut-off check), `after cut-off` (ever not published at a check at/after 11:00, or never available
before it), `mixed` (before the cut-off on some days only — not safe), `insufficient data` (fewer than
10 days with a pre-cut-off check). Only the check on D-1 for delivery day D counts; for THE gas day G
the relevant check is the one on G+1 ("is yesterday's gas price known at today's cut-off?"). Error rows
are ignored. It also writes `reports/publication_times_summary.md` (git-ignored; `--no-md` to skip).
`--cutoff HH:MM` reads the log against another cut-off (e.g. `--cutoff 11:11`, the time the live job runs).

**Caveat — Elia "day-ahead 11AM" run.** This run is issued *at* 11:00, so under the strict D-16 reading
("available before 11:00") it is expected to come out `after cut-off`, even though D-29 uses it as the
wind/solar same-time feature. If the log confirms that, the outcome goes to Henri as a **Proposed**
decision (e.g. move the cut-off to the live-job time 11:11, or fall back to an earlier run); it must not
be reinterpreted silently.

## Known data quirks
- Pumped storage (and sometimes offshore wind) is left EMPTY by ENTSO-E when it does not generate → treated as 0.
- BE nuclear = 0 MW from April to October 2026 (Doel 4 / Tihange 3 outage) — a regime the model must handle.
- `fc_gen_total` (A71) is on average ~440 MW below actual total generation: a weak baseline for `gen_total`.
- Gas before Oct 2021 is a MONTHLY step (published the month after) → it lags fast moves such as the Sep 2021 surge.
- Elia solar history starts Oct 2020; JAO flow-based starts Jun 2022; EUA ETC starts Oct 2021.
