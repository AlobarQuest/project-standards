import subprocess
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
