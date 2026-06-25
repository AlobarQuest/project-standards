---
name: backlog
description: Use when Devon says "put that on the backlog", "/backlog", "add to the backlog", or wants to record a future work item discovered mid-session. Captures via the portfolio CLI so it lands consistently (inbox-first, write-through to the repo's PROJECT.md when unambiguous).
---

# Backlog capture

For each item the user named, run once (from the repo's working directory so the project is inferred):

```bash
PYTHONPATH="$HOME/Projects/project-standards/src" python3 -m portfolio add "<item text>" --priority <P1|P2|P3|omit>
```

Rules:
- If the user named a different project, pass `--repo "$HOME/Projects/<name>"`.
- Capture verbatim intent; one `add` per distinct item; do not editorialize.
- Report where each landed: `[triaged]` = written to PROJECT.md, `[untriaged]` = held in inbox for `portfolio triage`.
- Never hand-edit PROJECT.md for backlog items — always go through `portfolio add`.
