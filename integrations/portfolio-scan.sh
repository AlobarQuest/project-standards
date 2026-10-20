#!/usr/bin/env bash
# Portfolio scan — the single command to refresh the portfolio rollup.
# Regenerates ~/.portfolio/portfolio.json + PORTFOLIO.md across all project roots.
# Run manually (`bash integrations/portfolio-scan.sh`) or via the daily LaunchAgent.
#
# EXIT CODES. 0 the scan ran with FACTORY_PR_TOKEN read from BWS. 3 the scan ran, but the token
# could not be read, so every check that needs it reported `unknown`. Anything else is the scan's
# own failure, passed through. launchd discards all of these: the Healthchecks check
# `portfolio-scan` and ~/.portfolio/scan.log are what record a run, and 3 pings `/fail` like any
# other non-zero exit.
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

LOG="$HOME/.portfolio/scan.log"
mkdir -p "$HOME/.portfolio"

# --- Liveness: the Healthchecks check `portfolio-scan` ----------------------
# Armed AFTER activation (which may re-exec this script, and would otherwise ping `/start` twice)
# and BEFORE anything that can fail, so a run that dies early still reports. The shape is
# orchestrator's scripts/sds-deadman.sh, kept here rather than sourced from that repository's
# working copy: the check is looked up by EXACT name through the Healthchecks Management API, with
# the one API key in BWS, so no ping URL is stored anywhere. It reports and never gates: a failure
# to resolve the check logs one line and the scan runs unwatched.
#
# The API key lives in a BWS project only the BROAD machine account can read; FACTORY_PR_TOKEN
# lives in Rotation / Keepers, which the NARROW `sds-operator` account reads by a direct grant on
# that one secret. Each identity is read from the Keychain
# into its own local variable and passed per call, never exported as BWS_ACCESS_TOKEN, because one
# ambient identity would make the other fetch fail. Every parsed `bws` call passes `--color no`
# with FORCE_COLOR and CLICOLOR_FORCE removed: either variable makes `bws` wrap its JSON in ANSI
# escapes even on a pipe.
HC_API_KEY_UUID="260cc8ad-f170-44cc-a672-b47000df3350"
HC_API="https://healthchecks.io/api/v3/checks/"
HC_CHECK_NAME="portfolio-scan"
HC_PING_URL=""

# Prints the ping URL of the check named $HC_CHECK_NAME, or one `[healthchecks]` line saying why
# there is none. Never fails the caller.
hc_resolve() {
  local broad key listing answer
  broad="$(security find-generic-password -s 'Claude' -a 'BWS_ACCESS_TOKEN_VPS_BACKUP' -w \
    2>/dev/null || true)"
  if [ -z "$broad" ]; then
    echo "[healthchecks] no broad BWS identity — this run is unwatched" >&2
    return 0
  fi
  key="$(env -u FORCE_COLOR -u CLICOLOR_FORCE BWS_ACCESS_TOKEN="$broad" \
    bws secret get "$HC_API_KEY_UUID" --output json --color no 2>/dev/null \
    | python3 -c 'import sys, json; print(json.load(sys.stdin)["value"])' 2>/dev/null || true)"
  if [ -z "$key" ]; then
    echo "[healthchecks] the API key could not be read — this run is unwatched" >&2
    return 0
  fi
  listing="$(curl -fsS --max-time 15 "$HC_API" -H "X-Api-Key: $key" 2>/dev/null || true)"
  # Exact name only: pinging a near-miss would report a run that did not happen. The Management
  # API omits `ping_url` for a read-only key, which is a different fault from a missing check.
  answer="$(printf '%s' "$listing" | HC_WANTED="$HC_CHECK_NAME" python3 -c 'import os, sys, json
wanted = os.environ["HC_WANTED"]
for check in json.load(sys.stdin).get("checks", []):
    if check.get("name") == wanted:
        print("URL " + check["ping_url"] if check.get("ping_url") else "NOPING")
        break
else:
    print("NONAME")' 2>/dev/null || true)"
  case "$answer" in
    "URL "*) printf '%s\n' "${answer#URL }" ;;
    NOPING) echo "[healthchecks] '$HC_CHECK_NAME' has no ping url (read-only key?)" >&2 ;;
    NONAME) echo "[healthchecks] no check named '$HC_CHECK_NAME'" >&2 ;;
    *) echo "[healthchecks] the check listing could not be read" >&2 ;;
  esac
  return 0
}

# `$1` is the suffix: empty for success, `/start` or `/fail`. A no-op when the check is unresolved.
hc_ping() {
  [ -n "$HC_PING_URL" ] || return 0
  curl -fsS --max-time 10 "${HC_PING_URL}$1" >/dev/null 2>&1 \
    || echo "[healthchecks] ping '${1:-/}' failed (non-fatal)" >&2
  return 0
}

# Every non-zero exit pings `/fail`, including 3, and the explicit exit keeps a failed ping from
# rewriting the run's answer on its way out.
hc_finish() {
  local rc=$?
  if [ "$rc" -eq 0 ]; then hc_ping ""; else hc_ping "/fail"; fi
  exit "$rc"
}

HC_PING_URL="$(hc_resolve)"
trap hc_finish EXIT
hc_ping "/start"

# --- Q2 factory-capability credentials -------------------------------------
# FACTORY_PR_TOKEN, APP_BRAIN_READ_KEY and DISPATCH_APP_PRIVATE_KEY_B64 let the
# nightly sweep answer "can the factory reach this repository?", "has the estate
# determined what landing on it does?" and "can the App that dispatches, reads the
# named check and lands the pull request reach it?". Absent, those checks report
# `unknown` with a named reason — never `pass` — so none of them fails the scan.
#
# THE THIRD ONE IS NOT LIKE THE OTHER TWO AND THE DIFFERENCE IS WORTH READING.
# The PAT and the brain key are tokens with a bounded reach. The App value is a
# PRIVATE KEY, and a key mints installation access tokens across everything the
# installation reaches — measured 2026-09-11: 75 repositories, 57 writable, with
# `contents: write` and `workflows: write`. Keeping it in credentials.env is a real
# expansion of what a 0600 plaintext file on this machine holds, and it is the one
# value there whose loss would matter beyond this estate.
#
# FACTORY_PR_TOKEN IS FETCHED FROM BWS ON EVERY RUN, AND ONLY FROM THERE (decided
# 2026-10-19, orchestrator ADR-0055 increment 7). Until then this script fetched
# nothing, deliberately: a conformance tool that reaches for secrets is a different
# security surface from one that reads files, and fetching would make
# project-standards a declared secret consumer. The SDS rotation executor now
# rotates this token, and a plaintext copy in credentials.env would go stale on the
# first rotation with nothing saying so. The executor verifies a scheduled reader
# through its Healthchecks check: `/start` is pinged before the fetch, and a run
# whose fetch comes back empty ends `/fail` (exit 3), so a successful run that
# started after the new value was stored proves the reader switched. The cost is
# accepted: this script now reads BWS with the narrow `sds-operator` identity, and
# the repository declares the UUID in .bws-secrets.toml. The Python kit itself still
# reads only its environment. security-standards' governance map does not require
# the declaration: its consumer list only seeds skeleton manifests, and verify
# checks deployed artifacts and OWNERSHIP.md, not consumers.
#
# The other two still arrive from the environment: export them before a manual run,
# or put them in ~/.portfolio/credentials.env, which lives outside every repository
# and is sourced here if it exists. A FACTORY_PR_TOKEN set there or in the calling
# shell is discarded below, before the fetch, so it can never stand in for BWS.
FACTORY_PR_TOKEN_UUID="a3240c2e-92d7-4b32-a726-b49b0135565a"
CREDENTIALS="$HOME/.portfolio/credentials.env"
if [ -f "$CREDENTIALS" ]; then
  # shellcheck source=/dev/null
  . "$CREDENTIALS"
fi
unset FACTORY_PR_TOKEN
FACTORY_PR_TOKEN=""
pat_reason=""
sds_identity="$(security find-generic-password -s 'Claude' -a 'BWS_ACCESS_TOKEN_SDS' -w \
  2>/dev/null || true)"
if [ -z "$sds_identity" ]; then
  pat_reason="no narrow BWS identity"
else
  FACTORY_PR_TOKEN="$(env -u FORCE_COLOR -u CLICOLOR_FORCE BWS_ACCESS_TOKEN="$sds_identity" \
    bws secret get "$FACTORY_PR_TOKEN_UUID" --output json --color no 2>/dev/null \
    | python3 -c 'import sys, json; print(json.load(sys.stdin)["value"])' 2>/dev/null || true)"
  [ -n "$FACTORY_PR_TOKEN" ] || pat_reason="bws fetch failed or returned empty"
fi
unset sds_identity
export FACTORY_PR_TOKEN APP_BRAIN_READ_KEY DISPATCH_APP_PRIVATE_KEY_B64
# Log WHICH credentials were present, never their values: an `unknown` in the
# digest is otherwise indistinguishable from a broken check, and this line is
# the difference between "nobody set the variable" and "the probe failed".
creds="pat=$([ -n "$FACTORY_PR_TOKEN" ] && echo bws || echo "no($pat_reason)")"
creds="$creds brain=$([ -n "${APP_BRAIN_READ_KEY:-}" ] && echo yes || echo no)"
creds="$creds app=$([ -n "${DISPATCH_APP_PRIVATE_KEY_B64:-}" ] && echo yes || echo no)"
# ---------------------------------------------------------------------------

# shellcheck source=integrations/_python.sh
. "$(dirname "${BASH_SOURCE[0]}")/_python.sh"
PY_BIN="$(portfolio_python)"

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
if [ -n "$pat_reason" ]; then
  echo "portfolio-scan: FACTORY_PR_TOKEN was not read from BWS ($pat_reason)" >&2
  exit 3
fi
