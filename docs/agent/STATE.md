# Project state (agent memory)

> Read at the start of every run. Rewrite the "Current" sections at the end of every run.
> Keep it short (< 80 lines). History goes to `docs/agent/journal/`, not here.

_Last updated: 2026-11-22 by Henri + Claude (initial setup)_

## Current phase
**Phase 1 — Data collection** (finishing) → Phase 2 — Cleaning, validation & EDA.

## What is true right now
- Code exists for every phase; unit tests pass; `demo` runs on synthetic data.
- First real ENTSO-E fetch done on Henri's laptop (2019-01-01 → 2026-10-27, 68,568 hourly rows).
  Validation report: `reports/validation_report.md`.
- TTF gas via yfinance is unreliable → CSV fallback (`data/external/ttf_prices.csv`) to finish.
- `gen_hydro` still ~29% missing after cleaning (D-20).
- Real data is not yet in the `data-latest` release until `fetch-data.yml` has run once
  (needs repository secret `ENTSOE_API_KEY`).

## Open questions (Henri decides)
- **Issue time**: Henri provisionally chose **11:11 Brussels on D-1** (16 Nov 2026) instead of
  10:00, so that data published at 11:00 is available. Not yet in `config.yaml`
  (`forecast.issue_hour_local: 10`) nor in `docs/DECISIONS.md`. Confirm once the
  publication-time log (release `pubtimes`) has ~2 weeks of data → then log as D-23.
- **Leakage risk (D-16)**: legal deadline for DA wind/solar & generation forecasts is 18:00 D-1.
  Which `fc_*` series are really published before the issue time?

## Next tasks (mirror of Notion, highest priority first)
1. Collect ~2 weeks of publication times (workflow `publication-times.yml`) → analyse → propose D-23.
2. TTF CSV fallback + EUA CSV → update Data Point Inventory availability.
3. Extend the ENTSO-E loader to neighbours' fundamentals (FR nuclear availability, D-18).
4. EDA insights (3–5) → Notion Phase 2 page.
5. Real walk-forward backtest + ablation per driver family.

## Last run
_None yet._
