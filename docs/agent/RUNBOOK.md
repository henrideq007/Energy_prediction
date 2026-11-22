# Agent runbook — rules of autonomy

These rules apply to every unattended run (scheduled task) and to interactive sessions unless
Henri explicitly says otherwise in the conversation.

## 1. One run = one task
1. Read `CLAUDE.md`, `docs/agent/STATE.md` and the latest file in `docs/agent/journal/`.
2. Pick **one** task in Notion All Tasks: `Owner = Agent`, `Status = To do`, current phase
   first, then `Priority` High → Low, then lowest `ID`. If none: write a short journal entry
   ("nothing to do"), propose up to 3 next tasks in STATE.md, notify Henri, stop.
3. Set the task to `In progress`.
4. Work on a branch `agent/T<ID>-<short-slug>` created from an up-to-date `main`.
5. Finish with a pull request, the Notion update, the journal entry and STATE.md.

## 2. Green light — the agent may do this alone
- Write/modify code under `src/`, `tests/`, `scripts/`, `notebooks/`, `api/`.
- Write/modify docs under `docs/` and `README.md` (results tables, methodology notes).
- Run `pytest`, `demo`, `validate`, `backtest`, `train`, `explain` locally in the session.
- Download releases (`gh release download`).
- Open a pull request to `main` and comment on its own PR.
- Update the Notion task (status, `PR`, `Notes`), add rows to **Experiments & Results**,
  add **proposed** entries to the Decision Log.
- Append to the phase "mémoire" Google Doc on Drive.

## 3. Red light — never, even if a task seems to ask for it
- Merge a PR, push to `main`, force-push, delete branches other than its own.
- Read, print or commit `.env` or any secret; commit data, models or forecasts.
- Modify `.github/workflows/`, `.claude/`, `CLAUDE.md` or this runbook (propose the change in
  the PR description instead).
- Change `config/config.yaml` values that alter results (issue time, lags, split dates,
  backtest window) without a decision accepted by Henri.
- Take a decision: a new D-xx is written with status **Proposed** and the task goes to
  `Needs review`. Only Henri marks a decision **Accepted**.
- Add paid data sources or new dependencies with a licence incompatible with a public repo.
- Delete Notion pages or Drive files.

## 4. Stop rules
- Tests fail after **two** fix attempts → push the branch, open a **draft** PR, set the task to
  `Blocked` with the reason in `Notes`, notify Henri, stop.
- The task is ambiguous or needs a decision → do not guess. Write the question in the task
  `Notes` and the journal, set `Blocked`, stop.
- A tool/connector fails twice (Notion, Drive, GitHub) → note it in the journal and continue
  without it if the code work is safe; otherwise stop.
- Time box: if the task is clearly larger than one run, split it — deliver the first coherent
  slice and create follow-up tasks in Notion (`Owner = Agent`, `Status = Backlog`).

## 5. Definition of done for a run
- [ ] `pytest` green (or draft PR + `Blocked`)
- [ ] `reviewer` sub-agent verdict recorded in the PR description
- [ ] PR open, linked in the Notion task (`PR`), task `Needs review`
- [ ] Journal entry `docs/agent/journal/YYYY-MM-DD.md` committed on the branch
- [ ] `docs/agent/STATE.md` updated on the branch
- [ ] Notification to Henri (French, 1 line): task, result, PR link

## 6. Henri's review loop
Henri reviews PRs (often from his phone). On merge he sets the Notion task to `Done`.
If he comments "changes requested", the next run treats that PR as its task before picking a
new one (look for open PRs from `agent/*` branches with unresolved review comments first).
