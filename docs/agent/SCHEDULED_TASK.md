# Nightly scheduled task (Claude)

Prompt used by the scheduled task that runs the project while Henri is away.
Each run starts a fresh session on this repository, so the prompt is self-contained.

```text
You are the autonomous agent of the Energy Prediction project
(GitHub henrideq007/Energy_prediction). Clone/open the repository, read CLAUDE.md,
docs/agent/STATE.md and docs/agent/RUNBOOK.md, then run the `next-task` skill exactly as
written: one task only, never merge or push to main, open a PR, update Notion
(All Tasks), the run journal and STATE.md through the `scribe` sub-agent.
Finish with a one-line summary in French for Henri (task, outcome, PR link), sent as a
push notification if possible.
```

Schedule: **Monday, Wednesday and Friday at 21:37 Europe/Brussels** (Henri reviews PRs the next day;
at most 2 agent PRs open at a time, see RUNBOOK §1).

## Before switching it on
1. Merge the PR that adds this setup.
2. Add the repository secret `ENTSOE_API_KEY` and run **Fetch data & retrain** once by hand
   (Actions tab → Run workflow) so `data-latest` exists.
3. In Notion All Tasks, set 1–3 well-scoped tasks to `Owner = Agent`, `Status = To do`.
4. Run the `next-task` skill manually once or twice and review the PRs.
5. Then create the scheduled task.
