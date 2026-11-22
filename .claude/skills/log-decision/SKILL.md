---
name: log-decision
description: Record a project decision for the Energy Prediction project in both docs/DECISIONS.md and the Notion Decision Log, with the right ID and status. Use whenever a choice changes results (data, features, split, metrics, issue time) or Henri states a decision.
---

# log-decision

## Who decides
- **Henri states it** (in conversation or PR comment) → status **Accepted**.
- **An agent suggests it** → status **Proposed — awaiting Henri**. The related task goes to
  `Needs review`. Never apply a proposed decision to `config/config.yaml`.

## Steps
1. Next ID = highest `D-xx` in `docs/DECISIONS.md` + 1.
2. Append a row to the table in `docs/DECISIONS.md`:
   `| D-xx | YYYY-MM-DD | Decision | Why (evidence, links) | Alternatives considered |`
   For proposed decisions prefix the Decision cell with `**[Proposed]**`.
3. Add the same entry to the Notion **Decision Log** (hub page
   https://app.notion.com/p/40c085376e958121a7d2d634e9d8371b) with the same ID and status.
4. If Accepted and it changes a parameter → update `config/config.yaml` in the same PR and
   mention the D-ID in a comment next to the value.
5. Mention the D-ID in the PR description and the journal.
