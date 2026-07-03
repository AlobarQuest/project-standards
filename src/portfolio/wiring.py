"""Static wiring verification for required_checks.

Verifies a declared check is INVOKED somewhere (workflow file + job, hook
registered in settings.json, LaunchAgent plist present). It does NOT prove the
check does real work — "wired but runs hollow" (the quality.yml incident) needs
execution evidence, a future drift-loop enhancement. See spec §4.
"""
import json
from pathlib import Path, PurePosixPath

import yaml

from . import config
from .matrix import NA, PASS, VIOLATION, CheckResult


def check_required_checks(repo: Path, entries: list, foundation: bool) -> CheckResult:
    if not entries:
        if foundation:
            details = [{"id": "checks.none-declared",
                        "message": "foundation repo declares no required_checks"}]
            return CheckResult("checks", VIOLATION, details=details)
        return CheckResult("checks", NA)

    details = [d for d in (_verify_entry(repo, e) for e in entries) if d]
    return CheckResult("checks", VIOLATION if details else PASS, details=details)


def _verify_entry(repo: Path, entry) -> dict | None:
    if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
            or not isinstance(entry.get("executor"), str)):
        return {"id": "checks.bad-executor",
                "message": f"malformed required_checks entry: {entry!r}"}
    check_id, executor = entry["id"], entry["executor"]
    kind, _, rest = executor.partition(":")
    if kind == "github-actions" and rest:
        return _verify_workflow(repo, check_id, rest)
    if kind == "hook" and rest:
        return _verify_hook(check_id, rest)
    if kind == "launchagent" and rest:
        return _verify_launchagent(check_id, rest)
    return {"id": "checks.bad-executor",
            "message": f"{check_id}: unparseable executor {executor!r}"}


def _verify_workflow(repo: Path, check_id: str, rest: str) -> dict | None:
    filename, _, job = rest.partition(":")
    path = repo / ".github" / "workflows" / filename
    if not path.is_file():
        return {"id": "checks.not-wired",
                "message": f"{check_id}: workflow {filename} not found"}
    if job:
        try:
            data = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError):
            return {"id": "checks.not-wired",
                    "message": f"{check_id}: workflow {filename} unreadable"}
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, dict) or job not in jobs:
            return {"id": "checks.not-wired",
                    "message": f"{check_id}: job {job!r} not in {filename}"}
    return None


def _iter_hook_commands(hooks_config: object):
    """Walk the hooks config, yielding every registered "command" string.

    Shape: {"EventName": [{"matcher": ..., "hooks": [{"type": "command",
    "command": "<string>"}, ...]}, ...]}. Walks defensively — tolerates
    missing keys and non-dict/non-list nodes rather than raising.
    """
    if not isinstance(hooks_config, dict):
        return
    for event_entries in hooks_config.values():
        if not isinstance(event_entries, list):
            continue
        for matcher_entry in event_entries:
            if not isinstance(matcher_entry, dict):
                continue
            inner_hooks = matcher_entry.get("hooks")
            if not isinstance(inner_hooks, list):
                continue
            for hook in inner_hooks:
                if isinstance(hook, dict) and isinstance(hook.get("command"), str):
                    yield hook["command"]


def _hook_name_registered(name: str, hooks_config: object) -> bool:
    for command in _iter_hook_commands(hooks_config):
        if any(PurePosixPath(token).name == name for token in command.split()):
            return True
    return False


def _verify_hook(check_id: str, name: str) -> dict | None:
    # A hook only runs if REGISTERED in settings.json — file existence in
    # ~/.claude/hooks/ proves deployment, not wiring (deployed != wired).
    # Matches against command basenames only (not a raw JSON substring) so
    # JSON keys ("command", "Stop") and path fragments ("gate.sh") can't
    # false-PASS a check that was never actually registered.
    path = config.claude_settings_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"id": "checks.not-wired",
                "message": f"{check_id}: cannot read hook registrations in {path}"}
    if not _hook_name_registered(name, data.get("hooks", {})):
        return {"id": "checks.not-wired",
                "message": f"{check_id}: hook {name!r} not registered in settings.json"}
    return None


def _verify_launchagent(check_id: str, label: str) -> dict | None:
    # Limitation (spec §4): plist existence != loaded; launchctl state is
    # runtime-flaky, so file presence is the accepted static proxy.
    plist = config.launchagents_dir() / f"{label}.plist"
    if not plist.is_file():
        return {"id": "checks.not-wired",
                "message": f"{check_id}: LaunchAgent {label}.plist not found"}
    return None
