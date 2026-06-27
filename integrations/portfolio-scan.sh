#!/usr/bin/env bash
# Portfolio scan — the single command to refresh the portfolio rollup.
# Regenerates ~/.portfolio/portfolio.json + PORTFOLIO.md across all project roots.
# Run manually (`bash integrations/portfolio-scan.sh`) or via the daily LaunchAgent.
set -euo pipefail

export PYTHONPATH="$HOME/Projects/project-standards/src"
LOG="$HOME/.portfolio/scan.log"
mkdir -p "$HOME/.portfolio"

ts="$(date '+%Y-%m-%d %H:%M:%S')"
if out="$(python3 -m portfolio scan 2>&1)"; then
  echo "[$ts] ok    $out" >> "$LOG"
  echo "$out"
else
  rc=$?
  echo "[$ts] FAIL(rc=$rc) $out" >> "$LOG"
  echo "$out" >&2
  exit "$rc"
fi
