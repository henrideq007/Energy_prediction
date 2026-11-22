#!/usr/bin/env python3
"""PreToolUse guard for unattended agent runs (see docs/agent/RUNBOOK.md §3).

Claude Code sends the tool call as JSON on stdin. Exit code 2 blocks the call and the
message on stderr is shown to the agent. Exit 0 lets it through.

To let Claude edit CLAUDE.md / .claude/ / workflows in an interactive session on your laptop,
start Claude Code with the environment variable ALLOW_AGENT_CONFIG_EDIT=1.
"""

from __future__ import annotations

import json
import os
import re
import sys

BASH_RULES: list[tuple[str, str]] = [
    (r"git\s+push\b.*\b(origin\s+)?(main|master)\b(?!-)", "Pushing to main is forbidden — open a PR from an agent/* branch."),
    (r"git\s+push\b.*(--force|-f\b|--force-with-lease)", "Force-push is forbidden."),
    (r"\bgh\s+pr\s+merge\b|pulls/\d+/merge|ccr/auto_merge", "Merging PRs is reserved to Henri."),
    (r"\bgit\s+merge\b.*\bmain\b|\bgit\s+checkout\s+main\b.*&&.*\bgit\s+merge\b", "Merging into main is reserved to Henri."),
    (r"(^|[\s;&|])(cat|less|more|head|tail|type|grep|sed|awk)\b[^|;&]*\.env(\s|$)", "Reading .env is forbidden (secrets)."),
    (r"\bgit\s+add\b[^;&|]*(\.env\b|data/|models/|forecasts/)", "Do not stage secrets, data, models or forecasts."),
    (r"\bprintenv\b|\benv\s*$|echo\s+\$ENTSOE", "Printing environment secrets is forbidden."),
    (r"\brm\s+-rf?\s+(/|~|\.\s*$|\.git\b|src\b|tests\b)", "Destructive rm is forbidden."),
]

PROTECTED_PATHS = (".env", ".github/workflows/", ".claude/", "CLAUDE.md", "docs/agent/RUNBOOK.md")


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool = event.get("tool_name", "")
    inp = event.get("tool_input", {}) or {}

    if tool == "Bash":
        cmd = inp.get("command", "")
        for pattern, msg in BASH_RULES:
            if re.search(pattern, cmd):
                print(f"Blocked by .claude/hooks/guard.py: {msg}", file=sys.stderr)
                return 2

    if tool in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = str(inp.get("file_path", "")).replace("\\", "/")
        if path.endswith("/.env") or path == ".env":
            print("Blocked by .claude/hooks/guard.py: .env holds secrets.", file=sys.stderr)
            return 2
        allow_cfg = os.environ.get("ALLOW_AGENT_CONFIG_EDIT") == "1"  # Henri, interactive only
        if tool != "Read" and not allow_cfg and any(p in path for p in PROTECTED_PATHS[1:]):
            print(
                "Blocked by .claude/hooks/guard.py: workflows, .claude/, CLAUDE.md and RUNBOOK.md "
                "are changed by Henri only — propose the change in the PR description.",
                file=sys.stderr,
            )
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
