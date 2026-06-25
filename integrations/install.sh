#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.claude/skills/backlog" "$HOME/.claude/hooks" "$HOME/Library/LaunchAgents"
cp "$HERE/backlog.skill.md" "$HOME/.claude/skills/backlog/SKILL.md"
install -m 0755 "$HERE/portfolio-nudge.sh" "$HOME/.claude/hooks/portfolio-nudge.sh"
cp "$HERE/com.devon.portfolio-scan.plist" "$HOME/Library/LaunchAgents/com.devon.portfolio-scan.plist"
launchctl unload "$HOME/Library/LaunchAgents/com.devon.portfolio-scan.plist" 2>/dev/null || true
launchctl load "$HOME/Library/LaunchAgents/com.devon.portfolio-scan.plist"
echo "Installed backlog skill, nudge hook, and weekly portfolio-scan LaunchAgent."
echo "NOTE: register portfolio-nudge.sh as a Stop hook in ~/.claude/settings.json manually."
