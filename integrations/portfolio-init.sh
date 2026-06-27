#!/usr/bin/env bash
# Onboard a project into the portfolio — scaffold its repo-root PROJECT.md (idempotent;
# never runs git init, never clobbers human-written fields). Run from INSIDE the repo,
# or pass a path. Defaults to the active tier.
#
#   portfolio-init.sh                         # onboard the current directory (active)
#   portfolio-init.sh /path/to/repo           # onboard a specific repo
#   portfolio-init.sh --parking               # park the current dir (long-tail/experiment)
#   portfolio-init.sh --purpose "does X"      # non-interactive (for lifecycle automation)
set -uo pipefail
export PYTHONPATH="$HOME/Projects/project-standards/src"
pf() { python3 -m portfolio "$@"; }

repo="$PWD"; tier="active"; purpose=""
while [ $# -gt 0 ]; do
  case "$1" in
    --tier)    tier="$2"; shift 2 ;;
    --parking) tier="parking"; shift ;;
    --purpose) purpose="$2"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *)  repo="$1"; shift ;;
  esac
done

repo="$(cd "$repo" 2>/dev/null && pwd)" || { echo "✗ no such directory" >&2; exit 1; }
existed=no; [ -f "$repo/PROJECT.md" ] && existed=yes

# init (idempotent) + optionally set purpose; echoes OK or PLACEHOLDER
apply() {
  python3 - "$repo" "$tier" "$1" <<'PY'
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.expanduser('~/Projects/project-standards/src'))
from portfolio.init import init_repo
from portfolio.manifest import read_manifest, write_manifest
repo, tier, purpose = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
init_repo(repo, tier=tier)
m = read_manifest(repo)
cur = (m.frontmatter or {}).get('purpose', '') or ''
is_placeholder = cur in ('', 'TODO: one-line purpose')
# Fill purpose only when blank/placeholder — never clobber a human-written one.
if purpose and is_placeholder:
    m.frontmatter['purpose'] = purpose
    write_manifest(m)
    cur = purpose
print('PLACEHOLDER' if cur in ('', 'TODO: one-line purpose') else 'OK')
PY
}

status="$(apply "$purpose")"
if [ "$status" = PLACEHOLDER ] && [ -z "$purpose" ] && [ -t 0 ]; then
  printf "One-line purpose for '%s' (blank to skip): " "$(basename "$repo")"
  read -r typed
  [ -n "$typed" ] && status="$(apply "$typed")"
fi

echo
if [ "$existed" = yes ]; then
  echo "PROJECT.md already existed — filled only blank fields (no clobber)."
else
  echo "Created PROJECT.md (tier=$tier)."
fi
echo "--- $repo/PROJECT.md ---"
cat "$repo/PROJECT.md"
echo "---"
if pf lint "$repo"; then echo "lint: clean ✅"; fi
[ "$status" = PLACEHOLDER ] && echo "⚠ purpose still 'TODO' — set it with --purpose or edit PROJECT.md."
echo "(commit PROJECT.md as part of your normal flow; the daily scan will pick it up.)"
