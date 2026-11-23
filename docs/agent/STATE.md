# Project state (agent memory)

> Read at the start of every run. Rewrite the "Current" sections at the end of every run.
> Keep it short (< 80 lines). History goes to `docs/agent/journal/`, not here.

_Last updated: 2026-11-23 by agent (T52, PR #6)_

## Current phase
**Phase 1 — Data collection: almost done** (2 of 3 exit criteria met) → next: Phase 2 — Cleaning, validation & EDA.

## What is true right now
- `dataset.parquet` (laptop): 68,784 h × 92 columns, 2019-01-01 → 2026-11-05. All 35 core columns
  < 2% missing (max 0.07%) — `reports/data_coverage.md`. `gen_hydro` fixed (0.03% missing, D-20).
- **Issue time = D-1 11:00 Brussels** (D-29, accepted, `forecast.issue_hour_local: 11`).
  Wind/solar same-time features = Elia "day-ahead 11AM" run (`elia_*_dayahead11hforecast`).
  ENTSO-E `fc_*` (= Elia 6PM run, published ~18:00 D-1) are **baseline-only** (`tso_forecast`);
  `features.leakage_check()` rejects them. The cloud forecast job runs at 11:11 (after the cut-off).
- Sources added in Phase 1 (decisions D-23..D-28, see `docs/DATA_SOURCES.md`):
  - Gas `ttf_gas`: Yahoo `TTF=F` + local cache (D-23) > manual CSV > THE daily hub price (Oct 2021 →)
    > IMF monthly back-fill (2019 → Sep 2021, flagged) (D-25). Yahoo only serves recent quotes.
  - Carbon `eua_carbon`: EEX EU ETS auction results 2018–2025 + `CO2.L` ETC × ratio for gaps/2026 (D-26).
  - Candidates, stored but ignored by `features.py` until an ablation test (D-24): `nb_*` (FR/NL/DE-LU
    load/wind/solar/gen forecasts), `unav_*_nuclear_mw` (outages as known at the issue time from the
    full revision history, D-27; BE only from 2022), `xch_*`, `fb_BE_*` (JAO, Jun 2022 →), `cap_BE_*`,
    `hydro_res_*`, `elia_*` other runs (D-28), `wfr_*` (France temperature), `cmd_coal_api2` (dead
    after Dec 2025).
- Dropped for v1: Open-Meteo ensemble (3 months of history only), coal (DP-047), paid data (D-17).
- **Backtest after D-29 done** (Henri, run `20261122-1954-8772`, walk-forward Nov 2025 → Oct 2026,
  `reports/leaderboard.md`). Price: XGBoost MAE 17.99 €/MWh, rMAE 0.49 (LightGBM 18.13; naive_day 28.87).
  Wind: LightGBM 207 MW beats `tso_forecast` 244. Solar (175 vs 168) and total (716 vs 566): `tso_forecast`
  still best — but it is the 18:00 run, not available at 11:00, so it is an upper bound, not a fair
  baseline (see T50). Pre-D-29 results are invalid.
- Data sharing: release `data-latest` holds `raw-cache.tar.gz` (data/raw + data/external) and the dataset.
  Bootstrapped from the laptop on 2026-11-22 (dataset 2019 → 2026-11-05, cache 81 MB; raw EEX files
  excluded from the public release, re-downloaded by the fetch); then `fetch-data.yml`
  restores the cache every Sunday, downloads only recent chunks, retrains and republishes.
  Agents read it with `python scripts/publish_data.py restore`. Secret `ENTSOE_API_KEY` is set.

## Open questions (Henri decides)
- Publication times still unverified for: Elia 11AM run, BE load forecast A65 (due 10:00), neighbours'
  A65/A69/A71, THE daily gas price, JAO final Core domain. Log (release `pubtimes`) = 48 rows, 3 checks
  all after 18:00 → insufficient; needs ~2 weeks (PR #6 adds the series + `--summarise`).
- The Elia 11AM run is issued *at* 11:00 → likely "after cut-off" under strict D-16. Once the log is
  sufficient: cut-off = live-job time 11:11, or fall back to another run? (no decision proposed yet)
- `config.yaml` comment on `commodities.publication_lag_days` still says D-1 10:00 (should be 11:00).
- BE nuclear outages before 2022 do not exist on ENTSO-E: use proxy `cap_BE_nuclear − gen_nuclear`
  (lag ≥ 48 h) or train nuclear-aware models on 2022+ only?

## Next tasks (mirror of Notion, highest priority first)
1. T52 pubtimes extension: in PR #6 (Needs review), then analysis after ~2 weeks of log —
   [agent] follow-up task (Backlog, earliest ~2026-12-07): `--summarise` at 11:00 and 11:11, propose
   decision; first check CI confirms Elia `ods086`/`ods087` IDs.
2. [agent] Phase 3 prep: publication lags for candidate families (xch ≥ 24–48 h, hydro_res ≥ 1 week, nb actuals ≥ 48 h).
3. Live path: Elia historical datasets lag ~2 days → near-real-time datasets (ods086 wind) for `predict_live`.
4. Henri: free AGSI+ key (`AGSI_API_KEY`), EEX 2026 auction xlsx → `data/raw/eex/`.
5. [agent] Phase 2: EDA insights (3–5) → Notion Phase 2 page; ablation per driver family (D-15).

## Last run
2026-11-23 (scheduled, agent): T52 — `src/energy_forecast/pubtimes.py` (Elia 11AM/day-ahead, THE, JAO
checks; `--summarise`), 61 tests green, reviewer APPROVE after DST fix. PR #6, task Needs review.
Journal: `docs/agent/journal/2026-11-23.md`.
