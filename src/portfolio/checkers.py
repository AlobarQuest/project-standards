import json
import os
import subprocess
import sys
from pathlib import Path

from . import config
from .matrix import CheckResult, PASS, VIOLATION, UNKNOWN
from .validator import lint


def _run(cmd, cwd=None, env=None, timeout=None):
    timeout = timeout or config.checker_timeout()
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                               text=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return None


def check_project(repo: Path) -> CheckResult:
    findings = lint(repo)
    details = [{"id": f"project.{f.code}", "message": f.message} for f in findings]
    status = VIOLATION if any(f.severity == "FAIL" for f in findings) else PASS
    return CheckResult("project", status, details=details)


def _security_detail(finding: dict) -> dict:
    line = finding.get("line")
    return {
        "id": f"security.{finding.get('rule_id')}",
        "message": f"{finding.get('file')}:{'-' if line is None else line} {finding.get('reason')}",
    }


def check_security(repo: Path) -> CheckResult:
    cmd = [sys.executable, "-m", "security_scan.cli", str(repo), "--category", "security"]
    env = {**os.environ, "PYTHONPATH": str(config.security_standards_src())}
    result = _run(cmd, env=env)
    if result is None:
        return CheckResult("security", UNKNOWN, note="security scanner unavailable")

    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return CheckResult("security", UNKNOWN, note="security scanner output unreadable")

    summary = payload.get("summary") if isinstance(payload, dict) else None
    by_severity = summary.get("by_severity") if isinstance(summary, dict) else None
    if not isinstance(by_severity, dict):
        return CheckResult("security", UNKNOWN, note="security scanner output unreadable")

    findings = payload.get("findings", [])
    if by_severity.get("BLOCK", 0) > 0:
        details = [_security_detail(f) for f in findings if f.get("severity") == "BLOCK"]
        return CheckResult("security", VIOLATION, details=details)

    details = [_security_detail(f) for f in findings]
    return CheckResult("security", PASS, details=details)


def _code_cmd() -> list[str]:
    return ["uv", "run", "code-standards", "check"]


def _code_detail(line: str) -> dict:
    tokens = line.split()
    if len(tokens) < 2:
        return {"id": "code.violation", "message": line}
    return {"id": f"code.{tokens[1]}", "message": line}


def check_code(repo: Path) -> CheckResult:
    if not (repo / ".code-standards.toml").exists():
        details = [{"id": "code.not-onboarded", "message": "repo not onboarded to code-standards"}]
        return CheckResult("code", VIOLATION, details=details)

    cmd = _code_cmd() + ["--repo", str(repo)]
    result = _run(cmd, cwd=config.code_standards_repo())
    if result is None:
        return CheckResult("code", UNKNOWN, note="code-standards unavailable")

    if result.returncode == 0:
        return CheckResult("code", PASS)

    if result.returncode == 1:
        details = [_code_detail(line) for line in result.stdout.splitlines() if line.strip()]
        return CheckResult("code", VIOLATION, details=details)

    stderr_lines = result.stderr.splitlines()
    first_line = stderr_lines[0] if stderr_lines else ""
    return CheckResult("code", UNKNOWN, note=f"code-standards could not run: {first_line}".rstrip())
