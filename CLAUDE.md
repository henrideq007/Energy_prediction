# CLAUDE.md — Energy Prediction (Belgian day-ahead price & production)

You are working on Henri Dequenne's portfolio project. This file is read at the start of every
session — interactive or unattended. Read it fully, then read `docs/agent/STATE.md` and
`docs/agent/RUNBOOK.md` before doing anything.

## 1. Goal
Forecast the 24 hourly values of day D for the Belgian (BE) bidding zone — day-ahead **price**
(`price_da`) and **production** (`gen_total`, `gen_solar`, `gen_wind`) — issued on D-1 before the
12:00 SDAC auction. Prove it on a walk-forward backtest, then run it live (CLI + FastAPI).
It is a public portfolio project: rigour, honesty about limits and clear documentation matter
more than squeezing the last 1% of MAE.

## 2. Where things live
| What | Where |
|---|---|
| Code | this repo, package `src/energy_forecast` |
| Parameters | `config/config.yaml` — change values here, never hard-code them |
| Methodology / data / decisions | `docs/METHODOLOGY.md`, `docs/DATA_SOURCES.md`, `docs/DECISIONS.md` |
| Agent memory between runs | `docs/agent/STATE.md` (current state) + `docs/agent/journal/` (one file per run) |
| Agent rules | `docs/agent/RUNBOOK.md` |
| Tasks (source of truth) | Notion **All Tasks** — data source `collection://3f203feb-d6db-4491-bde5-4bcfb9fd56c4` |
| Notion hub (Decision Log, Experiments & Results, Data Sources) | https://app.notion.com/p/40c085376e958121a7d2d634e9d8371b |
| Notion Roadmap (one page per phase) | https://app.notion.com/p/40c085376e95810983b7dd71b5b34918 |
| Google Drive project folder (one "mémoire" Doc + one "méthode" Doc per phase) | https://drive.google.com/drive/folders/1i_xuF9wb_fM7c_ohA4mm6bzi1B9xXReN |
| Real data | GitHub release `data-latest` (built by `.github/workflows/fetch-data.yml`) |
| Trained models | GitHub release `models-latest` |
| Publication-time log (D-16) | GitHub release `pubtimes` → `publication_times.csv` |

Notion task fields: `Task`, `Phase` (`0 Setup` … `6 Showcase`), `Status` (`Backlog`, `To do`,
`In progress`, `Blocked`, `Needs review`, `Done`), `Owner` (`Henri`, `Claude`, `Agent`),
`Priority`, `Code / file`, `Notes`, `PR`.
**Agents only pick tasks with `Owner = Agent` and `Status = To do`.**

## 3. Commands
```bash
pip install -r requirements.txt          # editable install with extras
pytest                                   # must pass before any PR
python -m energy_forecast demo           # full pipeline on synthetic data (no API key)
python -m energy_forecast validate       # needs data/processed/dataset.parquet
python -m energy_forecast backtest [--targets price_da] [--models ridge lightgbm] [--folds 3]
python -m energy_forecast train | predict | explain
gh release download data-latest -p "dataset.parquet" -D data/processed --clobber   # get real data
```
The cloud agent environment **cannot reach the ENTSO-E API** (`web-api.tp.entsoe.eu`).
Never try `energy_forecast fetch` there — use the `data-latest` release. Fetching is done by
GitHub Actions (secret `ENTSOE_API_KEY`) or on Henri's laptop.

## 4. Non-negotiable modelling rules
- **No leakage.** Only information available at issue time (D-1, currently 10:00 in config;
  Henri's provisional choice is 11:11 — see STATE.md). Actual load/generation lags >= 48 h, price
  lags >= 24 h (D-05). A TSO forecast is a same-time feature only if its publication time is
  verified (D-16). `features.leakage_check()` and the tests must keep passing.
- **Chronological splits only.** Walk-forward monthly folds, expanding window (D-07, D-21).
- **Baselines first.** A model is "better" only if it beats `naive_day` and
  `seasonal_naive_week` (and `tso_forecast` for production) on the walk-forward backtest (D-09).
- **Spikes and negative prices are kept** (flagged, never removed) (D-06).
- **New drivers need ablation proof** (D-15). **No paid data** (D-17).
- Report MAE (primary), rMAE vs weekly naive, direction accuracy, peak-hour hit (D-10).
- Synthetic results (`demo`) are never presented as market results.

## 5. Code conventions
- Python >= 3.10, type hints, small pure functions, logging via `logging.getLogger(__name__)`.
- Column naming: `price_da[_ZONE]`, `gen_<tech>`, `load_<actual|forecast>`, `fc_<series>`
  (TSO forecasts), `w_<location>_<variable>` (weather). Keep names explicit and documented in
  `docs/DATA_SOURCES.md` with their DP-ID.
- Every new function with logic gets a unit test in `tests/`. Tests must not hit the network.
- Docs, code comments, commit messages, Notion and PRs: **English** (D-13).
  Messages and run summaries addressed to Henri: **French**.

## 6. Security
- Never read, print, copy or commit `.env` or any token. Secrets live only in `.env` (laptop)
  and GitHub Secrets.
- Never commit data, models or forecasts (`data/`, `models/`, `forecasts/` are git-ignored).

## 7. How to work autonomously
Follow `docs/agent/RUNBOOK.md`. The nightly entry point is the `next-task` skill.
Specialised sub-agents live in `.claude/agents/`: `data-engineer`, `ml-researcher`,
`reviewer`, `scribe`.
