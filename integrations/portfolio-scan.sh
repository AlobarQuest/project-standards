#!/usr/bin/env bash
# Portfolio scan — the single command to refresh the portfolio rollup.
# Regenerates ~/.portfolio/portfolio.json + PORTFOLIO.md across all project roots.
# Run manually (`bash integrations/portfolio-scan.sh`) or via the daily LaunchAgent.
set -euo pipefail

export PYTHONPATH="$HOME/Projects/project-standards/src"

# shellcheck source=integrations/_python.sh
. "$(dirname "${BASH_SOURCE[0]}")/_python.sh"
PY_BIN="$(portfolio_python)"
LOG="$HOME/.portfolio/scan.log"
mkdir -p "$HOME/.portfolio"

# --- Q2 factory-capability credentials -------------------------------------
# FACTORY_PR_TOKEN and APP_BRAIN_READ_KEY let the nightly sweep answer "can the
# factory reach this repository?" and "has the estate determined what landing on
# it does?". Absent, those checks report `unknown` with a named reason — never
# `pass` — so this block is optional and never fails the scan.
#
# NEITHER THIS SCRIPT NOR THE KIT FETCHES FROM BWS, deliberately. A conformance
# tool that reaches for secrets is a different security surface from one that
# reads files, and a BWS reference here would make project-standards a declared
# secret consumer — obliging it to carry a .bws-secrets.toml manifest and an
# entry in security-standards' governance map, for a repository that handles no
# secrets of its own. The values arrive from the environment: export them before
# a manual run, or put them in ~/.portfolio/credentials.env, which lives outside
# every repository and is sourced here if it exists. Populate that file from BWS
# by hand; the UUIDs are recorded in factory-runner's .bws-secrets.toml and in
# the Q2 build report.
CREDENTIALS="$HOME/.portfolio/credentials.env"
if [ -f "$CREDENTIALS" ]; then
  # shellcheck source=/dev/null
  . "$CREDENTIALS"
  export FACTORY_PR_TOKEN APP_BRAIN_READ_KEY
fi
# Log WHICH credentials were present, never their values: an `unknown` in the
# digest is otherwise indistinguishable from a broken check, and this line is
# the difference between "nobody set the variable" and "the probe failed".
creds="pat=$([ -n "${FACTORY_PR_TOKEN:-}" ] && echo yes || echo no)"
creds="$creds brain=$([ -n "${APP_BRAIN_READ_KEY:-}" ] && echo yes || echo no)"
# ---------------------------------------------------------------------------

ts="$(date '+%Y-%m-%d %H:%M:%S')"
if out="$("$PY_BIN" -m portfolio scan 2>&1)"; then
  echo "[$ts] ok    [$creds] $out" >> "$LOG"
  echo "$out"
else
  rc=$?
  echo "[$ts] FAIL(rc=$rc) [$creds] $out" >> "$LOG"
  echo "$out" >&2
  exit "$rc"
fi
