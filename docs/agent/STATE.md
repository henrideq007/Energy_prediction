# Project state (agent memory)

> Read at the start of every run. Rewrite the "Current" sections at the end of every run.
> Keep it short (< 80 lines). History goes to `docs/agent/journal/`, not here.

_Last updated: 2026-11-25 by agent (T11, PR #7)_

## Current phase
**Phase 2 — Cleaning, validation & EDA: started.** EDA done (T11, PR #7, Needs review); 5 insights on the Notion
Phase 2 page. Phase 1 still open on one exit criterion: publication times (pubtimes log, T53 from ~2026-12-07).

## What is true right now
- `dataset.parquet`: 68,784 h × 92 columns, 2019-01-01 → 2026-11-05; core columns < 2% missing. `dataset_clean.parquet`
  (EDA input) 68,759 h to 2026-11-04.
- **Issue time = D-1 11:00 Brussels** (D-29). Wind/solar same-time features = Elia "day-ahead 11AM" run.
  ENTSO-E `fc_*` (6PM run) are **baseline-only** (`tso_forecast`); `features.leakage_check()` rejects them.
- Sources D-23..D-28 (see `docs/DATA_SOURCES.md`): `ttf_gas` = Yahoo/THE daily (Oct 2021 →) + IMF monthly
  proxy 2019 → Sep 2021 (35% of hours, flagged — do not call it "TTF" in analyses); `eua_carbon` = EEX + ETC ratio.
  Candidate families (`nb_`, `unav_`, `xch_`, `fb_`, `cap_BE_`, `hydro_res_`, `elia_` other runs, `wfr_`, `cmd_`) stay
  out of features until ablation (D-24).
- Backtest after D-29 (Henri, run `20261122-1954-8772`, Nov 2025 → Oct 2026): price XGBoost MAE 17.99 €/MWh,
  rMAE 0.49 (naive_day 28.87); wind LightGBM 207 MW beats `tso_forecast` 244; solar/total `tso_forecast` still best
  (but 18:00 run = upper bound, T50).
- **EDA (T11)**: `src/energy_forecast/eda.py`, `scripts/run_eda.py` → `reports/eda/eda_summary.md`. Mean price
  39.8 / 187.6 / 87.6 €/MWh (pre / crisis / post); merit-order slope 8.1 / 34.9 / 18.3 €/MWh per GW;
  negative hours 71 (2019) → 519 (2025), 72% at 11–16h; H2 2026 rising-gas regime (gas 45 → 104, BE 112 → 248).
  Candidate ablations (D-15): residual load × lagged gas, RES share, gas-level/regime feature.
- Data sharing: release `data-latest` (dataset + raw cache), refreshed weekly by `fetch-data.yml`.
  **Cloud caveat:** `python scripts/publish_data.py restore` fails in cloud sessions (`gh release download` →
  GraphQL 403). Workaround until fixed: download assets via the REST endpoint
  (`gh api repos/<owner>/<repo>/releases/assets/<id>` with `Accept: application/octet-stream`).
- pytest: 85 passed on `agent/T11-eda-price-regimes`.

## Open questions (Henri decides)
- PR #7 questions: (1) backtest metrics split by sub-period (rising-gas Aug–Oct 2026 folds)? → task created;
  (2) restore fix → task created; (3) Notion T52 back at "To do" although PR #6 merged — set Done?;
  (4) 2026-06-24 19–21h BE prices 553 / 887 / 933 €/MWh (dataset max): cross-check?
- Publication times unverified: Elia 11AM run, BE load forecast A65 (EDA residual load uses it — reviewer asks
  to confirm < 11:00), neighbours' A65/A69/A71, THE, JAO. Log needs ~2 weeks (T53, earliest ~2026-12-07).
- Elia 11AM run issued *at* 11:00 → likely "after cut-off" under strict D-16: cut-off = 11:11 live-job time, or
  another run? (no decision proposed yet)
- `config.yaml` comment on `commodities.publication_lag_days` still says D-1 10:00 (should be 11:00).
- BE nuclear outages before 2022 missing on ENTSO-E: proxy `cap_BE_nuclear − gen_nuclear` (lag ≥ 48 h) or
  nuclear-aware models on 2022+ only?

## Next tasks (mirror of Notion, highest priority first)
1. [agent] T45 (Phase 3, To do): apply publication lags to candidate families (xch ≥ 24–48 h, hydro_res ≥ 1 week,
   nb actuals ≥ 48 h) before ablation.
2. [agent] Fix `publish_data.py restore` for cloud sessions (REST release-asset download) — Phase 1, Backlog, High.
3. [agent] T53: analyse pubtimes log with `--summarise` at 11:00 and 11:11 (incl. A65), earliest ~2026-12-07.
4. [agent] Backtest metrics split by sub-period (rising-gas H2 2026) — Phase 4, Backlog, Medium.
5. [agent] Ablations from EDA (D-15): residual load × lagged gas, RES share, gas regime.
6. Henri: review PR #7; T52 status; AGSI+ key; EEX 2026 auction xlsx → `data/raw/eex/`.

## Last run
2026-11-25 (scheduled, agent): T11 EDA — `eda.py` + `run_eda.py`, 85 tests green, reviewer APPROVE after gas-label
fix. PR #7, task Needs review. Journal: `docs/agent/journal/2026-11-25.md`.
