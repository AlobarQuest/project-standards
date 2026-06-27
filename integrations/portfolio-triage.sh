#!/usr/bin/env bash
# Interactive inbox triage — assign each captured-but-unplaced item into a repo's
# PROJECT.md. These are items that couldn't auto-place (ambiguous repo or dirty tree).
# Run: bash integrations/portfolio-triage.sh
# For each item: type a repo NAME (e.g. 'brain'), a full PATH, [s]kip, or [q]uit.
set -uo pipefail
export PYTHONPATH="$HOME/Projects/project-standards/src"
pf() { python3 -m portfolio "$@"; }

resolve_repo() {
  local name="$1"
  case "$name" in
    /*) [ -d "$name" ] && { echo "$name"; return 0; }; return 1 ;;
  esac
  for root in "$HOME/Projects" "$HOME/Developer"; do
    [ -d "$root/$name" ] && { echo "$root/$name"; return 0; }
  done
  return 1
}

# Collect untriaged items (portable: no mapfile — macOS /bin/bash is 3.2).
items=()
while IFS= read -r l; do [ -n "${l// /}" ] && items+=("$l"); done < <(pf triage)

if [ "${#items[@]}" -eq 0 ]; then
  echo "Inbox is empty — nothing to triage. ✅"
  exit 0
fi

echo "${#items[@]} item(s) to triage."
assigned=0
for line in "${items[@]}"; do
  id="${line%%[[:space:]]*}"
  echo
  echo "──────────────────────────────────────────────────────────────"
  echo "$line"
  echo "──────────────────────────────────────────────────────────────"
  printf "→ assign to repo (name / path / [s]kip / [q]uit): "
  read -r ans || break
  case "$ans" in
    ""|s|S|skip) echo "  skipped (stays in inbox)"; continue ;;
    q|Q|quit) echo "  quitting"; break ;;
    *)
      if repo="$(resolve_repo "$ans")"; then
        if pf triage --assign "$id" --repo "$repo"; then
          echo "  ✓ written to $repo/PROJECT.md"
          assigned=$((assigned + 1))
        else
          echo "  ✗ assign failed — left in inbox"
        fi
      else
        echo "  ✗ no repo '$ans' under ~/Projects or ~/Developer — left in inbox"
      fi
      ;;
  esac
done

echo
echo "Done — triaged $assigned item(s)."
if [ "$assigned" -gt 0 ]; then
  echo "Refreshing rollup (portfolio scan)…"
  pf scan
fi
