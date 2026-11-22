# Project state (agent memory)

> Read at the start of every run. Rewrite the "Current" sections at the end of every run.
> Keep it short (< 80 lines). History goes to `docs/agent/journal/`, not here.

_Last updated: 2026-11-22 by Henri + Claude (Phase 1 merge + D-29; data-cache sharing)_

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
- Old backtest/leaderboard numbers were computed with leaky `fc_*` features → **invalid, re-run**.
- Data sharing: release `data-latest` holds `raw-cache.tar.gz` (data/raw + data/external) and the dataset.
  Bootstrap once from the laptop (`python scripts/publish_data.py publish`); then `fetch-data.yml`
  restores the cache every Sunday, downloads only recent chunks, retrains and republishes.
  Agents read it with `python scripts/publish_data.py restore`. Secret `ENTSOE_API_KEY` is set.

## Open questions (Henri decides)
- Publication times still unverified for: BE load forecast A65 (due 10:00), neighbours' A65/A69/A71,
  THE daily gas price, JAO final Core domain. The `publication-times.yml` log (release `pubtimes`)
  must cover ~2 weeks first.
- BE nuclear outages before 2022 do not exist on ENTSO-E: use proxy `cap_BE_nuclear − gen_nuclear`
  (lag ≥ 48 h) or train nuclear-aware models on 2022+ only?

## Next tasks (mirror of Notion, highest priority first)
1. [agent] Re-run the walk-forward backtest with the D-29 features (old results invalid).
2. [agent] Extend `scripts/check_publication_times.py` to the Elia 11AM run, THE gas and JAO;
   then analyse the `pubtimes` log → confirm/adjust same-time use of A65, neighbours, THE, JAO.
3. [agent] Phase 3 prep: publication lags for candidate families (xch ≥ 24–48 h, hydro_res ≥ 1 week, nb actuals ≥ 48 h).
4. Live path: Elia historical datasets lag ~2 days → near-real-time datasets (ods086 wind) for `predict_live`.
5. Henri: free AGSI+ key (`AGSI_API_KEY`), EEX 2026 auction xlsx → `data/raw/eex/`.
6. [agent] Phase 2: EDA insights (3–5) → Notion Phase 2 page; ablation per driver family (D-15).

## Last run
2026-11-22 (interactive, Henri + Claude): merged origin/main (agent setup, Yahoo TTF cache) into the
Phase 1 work, renumbered local decisions to D-24..D-29, implemented D-29. 34 tests green. Pushed to `main`
with Henri's explicit one-off authorisation.
