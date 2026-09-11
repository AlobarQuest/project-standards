#!/usr/bin/env bash
# Portfolio scan — the single command to refresh the portfolio rollup.
# Regenerates ~/.portfolio/portfolio.json + PORTFOLIO.md across all project roots.
# Run manually (`bash integrations/portfolio-scan.sh`) or via the daily LaunchAgent.
set -euo pipefail

export PYTHONPATH="$HOME/Projects/project-standards/src"
# ACTIVATION — a merged change is not live on this machine until the code is pulled. The estate's
# Dependabot cascade stops at the merge, which is complete for a repository whose landing redeploys
# a hosted application and incomplete for this one, whose code runs from a working copy here
# (orchestrator ADR-0031). Best-effort by construction: the helper prints one `[activation]` line
# and returns 0 whatever it finds, so this job is never gated on being able to update itself. It
# re-execs this script when HEAD moves, because bash reads a script incrementally by byte offset
# and the file it just rewrote is this one.
_SDS_ACTIVATE="$HOME/.claude/bin/activate-checkout.sh"
if [ -r "$_SDS_ACTIVATE" ]; then
    # shellcheck source=/dev/null
    . "$_SDS_ACTIVATE"
else
    activate_checkout() {
        echo "[activation] helper missing at $HOME/.claude/bin/activate-checkout.sh —" \
             "this run is not activated"
    }
fi
_SDS_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
activate_checkout "$_SDS_REPO_ROOT" "$0" "$@"


# shellcheck source=integrations/_python.sh
. "$(dirname "${BASH_SOURCE[0]}")/_python.sh"
PY_BIN="$(portfolio_python)"
LOG="$HOME/.portfolio/scan.log"
mkdir -p "$HOME/.portfolio"

# --- Q2 factory-capability credentials -------------------------------------
# FACTORY_PR_TOKEN, APP_BRAIN_READ_KEY and DISPATCH_APP_PRIVATE_KEY_B64 let the
# nightly sweep answer "can the factory reach this repository?", "has the estate
# determined what landing on it does?" and "can the App that dispatches, reads the
# named check and lands the pull request reach it?". Absent, those checks report
# `unknown` with a named reason — never `pass` — so this block is optional and
# never fails the scan.
#
# THE THIRD ONE IS NOT LIKE THE OTHER TWO AND THE DIFFERENCE IS WORTH READING.
# The PAT and the brain key are tokens with a bounded reach. The App value is a
# PRIVATE KEY, and a key mints installation access tokens across everything the
# installation reaches — measured 2026-09-11: 75 repositories, 57 writable, with
# `contents: write` and `workflows: write`. Adding it to this file is a real
# expansion of what a 0600 plaintext file on this machine holds. It is here rather
# than fetched for the same reason as the other two (below), and it is the one
# value in it whose loss would matter beyond this estate.
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
  export FACTORY_PR_TOKEN APP_BRAIN_READ_KEY DISPATCH_APP_PRIVATE_KEY_B64
fi
# Log WHICH credentials were present, never their values: an `unknown` in the
# digest is otherwise indistinguishable from a broken check, and this line is
# the difference between "nobody set the variable" and "the probe failed".
creds="pat=$([ -n "${FACTORY_PR_TOKEN:-}" ] && echo yes || echo no)"
creds="$creds brain=$([ -n "${APP_BRAIN_READ_KEY:-}" ] && echo yes || echo no)"
creds="$creds app=$([ -n "${DISPATCH_APP_PRIVATE_KEY_B64:-}" ] && echo yes || echo no)"
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
