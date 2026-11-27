# Project state (agent memory)

> Read at the start of every run. Rewrite the "Current" sections at the end of every run.
> Keep it short (< 80 lines). History goes to `docs/agent/journal/`, not here.

_Last updated: 2026-11-27 by agent (T45, PR #8)_

## Current phase
**Phase 3 — Features & split: started** (T45 candidate lags, PR #8). Phase 2 EDA in PR #7 (T11, Needs review).
Phase 1 still open on one exit criterion: publication times (pubtimes log, T53 from ~2026-12-07).

**Two agent PRs in flight** (next run: review queue = 2 → no new task unless Henri merges or requests changes):
- PR #7 `agent/T11-eda-price-regimes` — EDA (`eda.py`, `run_eda.py`); has its own STATE/journal (2026-11-25).
- PR #8 `agent/T45-candidate-pub-lags` — candidate publication lags; this STATE. Merge conflict on this file
  expected: keep both "What is true" bullets.

## What is true right now
- `dataset.parquet`: 68,784 h × 92 columns, 2019-01-01 → 2026-11-05; core columns < 2% missing.
- **Issue time = D-1 11:00 Brussels** (D-29). Wind/solar same-time features = Elia "day-ahead 11AM" run.
  ENTSO-E `fc_*` (6PM run) are **baseline-only** (`tso_forecast`); `features.leakage_check()` rejects them.
- Sources D-23..D-28 (`docs/DATA_SOURCES.md`): `ttf_gas` = Yahoo/THE daily (Oct 2021 →) + IMF monthly proxy
  2019 → Sep 2021 (flagged); `eua_carbon` = EEX + ETC ratio.
- Backtest after D-29 (Henri, run `20261122-1954-8772`, Nov 2025 → Oct 2026): price XGBoost MAE 17.99 €/MWh,
  rMAE 0.49 (naive_day 28.87); wind LightGBM 207 MW beats `tso_forecast` 244; solar/total `tso_forecast` still best
  (but 18:00 run = upper bound, T50).
- **Candidate families (T45, PR #8, D-30 proposed):** `features.candidate_features` + hard floors
  `CANDIDATE_MIN_LAG_H`, config `candidate_features` (10 families), opt-in only (`backtest --candidates FAMILY ...`).
  Lags: xch / nb actuals 48+168 h; nb forecasts, fb_BE, Elia week-ahead & latest day-ahead 24+168 h (until T53);
  Elia measured 48+168 h; hydro_res 336 h; unav 0 h (BE NaN before 2022 + proxy `nuc_BE_gap_proxy_lag48`);
  cap_BE, wfr, coal 0 h; AGSI 48 h; DST mask on 25-h autumn day. Real data: default matrix byte-identical to `main`;
  all families 77 candidate cols, `leakage_check` empty. No model metrics yet.
- **EDA (T11, PR #7):** mean price 39.8 / 187.6 / 87.6 €/MWh (pre / crisis / post); H2 2026 rising-gas regime.
- pytest: 130 passed on `agent/T45-candidate-pub-lags` (85 on the T11 branch).
- Data sharing: release `data-latest` (dataset + raw cache), refreshed weekly by `fetch-data.yml`.
  **Cloud caveat:** `python scripts/publish_data.py restore` fails in cloud sessions (2026-11-25 and 2026-11-27,
  `gh release download` → GraphQL). Workaround: `gh api -H 'Accept: application/octet-stream'
  repos/<owner>/<repo>/releases/assets/<id>`.

## Open questions (Henri decides)
- PR #8: (1) accept D-30? — ID clash: Notion already has a "D-30" (physical post-processing, 2026-11-03) not in
  `docs/DECISIONS.md`; renumber one; (2) BE unav `valid_from` later than 2022-01-01 (H1 2022 looks under-recorded)?;
  (3) OK for `price_da_lag24` DST fix (changes results)?; (4) ablations to a separate reports dir?
- PR #7: backtest by sub-period; T52 Notion status; 2026-06-24 price spike cross-check.
- Publication times unverified: Elia 11AM run, BE A65 load forecast, neighbours' A65/A69/A71, THE, JAO (T53).
- Elia 11AM run issued *at* 11:00 → cut-off 11:11 (live-job time) or another run? (no decision proposed yet)

## Next tasks (mirror of Notion, highest priority first)
1. [agent] Ablation per candidate family (D-15) with `backtest --candidates`, separate reports dir — Phase 3,
   Backlog, High; needs D-30 accepted + PR #8 merged (agent side of Henri's T35).
2. [agent] T53: pubtimes log analysis with `--summarise` at 11:00 and 11:11 (incl. A65), earliest ~2026-12-07.
3. [agent] T54: fix `publish_data.py restore` for cloud sessions (REST asset download) — Phase 1, Backlog, High.
4. [agent] Backtest metrics split by sub-period (rising-gas H2 2026) — Phase 4, Backlog, Medium.
5. [agent] Low: `price_da_lag24` DST fix (needs Henri's OK); BE nuclear unav H1 2022 vs raw A80 (data-engineer).
6. Henri: review PR #7 and PR #8; decide D-30 (+ ID clash); AGSI+ key (`AGSI_API_KEY`); EEX 2026 auction xlsx
   → `data/raw/eex/`.

## Last run
2026-11-27 (scheduled, agent): T45 — candidate publication lags, 130 tests green (69 new), reviewer APPROVE after
3 leak fixes. PR #8, task Needs review. Journal: `docs/agent/journal/2026-11-27.md`.
