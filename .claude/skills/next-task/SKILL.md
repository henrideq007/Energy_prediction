---
name: next-task
description: Nightly autonomous run for the Energy Prediction project — pick the next agent task in Notion, implement it on a branch with the right sub-agent, test, review, open a PR, update Notion/Drive/journal/STATE and notify Henri. Use when asked to "run the next task", "continue the project" or from the scheduled task.
---

# next-task — one autonomous run

Follow `docs/agent/RUNBOOK.md` strictly. One task per run. Never merge, never push to `main`.

## Step 0 — Prepare
```bash
git checkout main && git pull --ff-only
pip install -r requirements.txt -q
pytest -q          # baseline must be green; if red on main: stop, notify Henri
```
Read `CLAUDE.md`, `docs/agent/STATE.md`, the latest `docs/agent/journal/*.md`.
Get the real data: `python scripts/publish_data.py restore` (if the release is missing, only
tasks that don't need real data can be done — say so in the journal).
✅ Checkpoint: main is green and you know the current phase.

## Step 1 — Pending reviews first
`gh api "repos/henrideq007/Energy_prediction/pulls?state=open" --jq '.[] | select(.head.ref|startswith("agent/")) | "\(.number) \(.head.ref)"'`
then `gh api repos/henrideq007/Energy_prediction/pulls/<n>/comments` and `.../issues/<n>/comments`
— if a PR has review comments from Henri asking for changes, that PR is this run's task:
check out its branch, address the comments, go to Step 4.
If **2 or more** agent PRs are open with no change request, stop here: notify Henri
(`Énergie ⏸️ 2 PR en attente de relecture — rien de nouveau lancé`) and end the run.
Read the journal/STATE of open agent branches (`git fetch origin <branch>` +
`git show origin/<branch>:docs/agent/STATE.md`) so you don't redo work in flight.

## Step 2 — Pick the task
Query Notion All Tasks (`collection://3f203feb-d6db-4491-bde5-4bcfb9fd56c4`):
`Owner = Agent` AND `Status = To do`; order by phase (current phase first), Priority
(High > Medium > Low), ID ascending. Take the first one not already covered by an open PR.
If Notion is unreachable: take the first `[agent]` item of STATE.md "Next tasks" and note it.
- None → journal "nothing to do", propose up to 3 tasks in STATE.md "Next tasks"
  (do not create them as `To do`; create them in Notion as `Backlog`, `Owner = Agent`),
  notify Henri, stop.
- Set it to `In progress`.
- Branch: `git checkout -b agent/T<ID>-<slug>`.
✅ Checkpoint: exactly one task in progress, on its own branch.

## Step 3 — Implement (delegate)
Pick the sub-agent by scope:
- loaders / cleaning / publication times / `docs/DATA_SOURCES.md` → **data-engineer**
- EDA / features / backtest / ablation / models / SHAP → **ml-researcher**
- both → data-engineer first, then ml-researcher.
Give it: the task title + Notes from Notion, the acceptance criteria you infer (write them
down), and the relevant CLAUDE.md rules. If the task needs a decision, stop (RUNBOOK §4).
Then run `pytest -q` yourself. Max two fix rounds.
✅ Checkpoint: tests green, changes limited to the task scope.

## Step 4 — Review
Run the **reviewer** sub-agent on the branch. If `CHANGES NEEDED` with blocking issues: fix
them (delegate back) once, re-run the reviewer. Still blocking → draft PR + `Blocked`.
✅ Checkpoint: reviewer verdict recorded.

## Step 5 — Commit and PR
```bash
git add -A && git status   # verify: no .env, no data/, models/, forecasts/
git commit -m "T<ID>: <title>"
git push -u origin agent/T<ID>-<slug>
gh api repos/henrideq007/Energy_prediction/pulls -f title="T<ID>: <title>" \
  -f head="agent/T<ID>-<slug>" -f base=main -F body=@<tmp file>   # add -F draft=true when blocked
```
Note: in cloud sessions GitHub GraphQL is unavailable, so `gh pr create/list/view` fail —
always use the REST calls above (`gh api ...`).
PR body (English): Goal · What changed · How it was tested (commands) · Results (real data
only) · Reviewer verdict · Questions for Henri · Notion task link.

## Step 6 — Record
Run the **scribe** sub-agent with: task, branch, PR URL, outcome, changes, results, reviewer
verdict, questions. It updates Notion, Drive, the journal and STATE.md, and commits the
journal + STATE on the branch → `git push`.
✅ Checkpoint: Notion task is `Needs review` (or `Blocked`) with the PR link.

## Step 7 — Notify Henri (French, one line, < 200 characters)
Examples:
- `Énergie ✅ T42 « Fallback TTF CSV » — PR prête à relire : <url>`
- `Énergie ⛔ T43 bloquée : décision nécessaire sur l'heure d'émission — voir Notion`
Use the push-notification tool if available; otherwise make it the final message.
