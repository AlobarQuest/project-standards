#!/usr/bin/env bash
# Non-blocking Stop hook: warn (never block) if the session's repo has a missing
# or invalid PROJECT.md. (Staleness is reported by the weekly scan, not here.)
set -euo pipefail
REPO="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$REPO" ] && exit 0
OUT="$(PYTHONPATH="$HOME/Projects/project-standards/src" "$PY_BIN" -m portfolio lint "$REPO" 2>/dev/null || true)"
if echo "$OUT" | grep -q "FAIL missing_manifest"; then
  echo "💡 portfolio: this repo has no PROJECT.md — run 'portfolio init .' to add one." >&2
elif echo "$OUT" | grep -q "FAIL"; then
  echo "💡 portfolio: PROJECT.md has issues:" >&2
  echo "$OUT" | grep "FAIL" >&2
fi
exit 0
