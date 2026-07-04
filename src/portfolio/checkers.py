import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import config
from .matrix import PASS, UNKNOWN, VIOLATION, CheckResult
from .validator import lint


def _run(cmd, cwd=None, env=None, timeout=None):
    timeout = timeout or config.checker_timeout()
    try:
        return subprocess.run(
            cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout
        )
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
    installed = config.code_standards_repo() / ".venv" / "bin" / "code-standards"
    if installed.is_file():
        return [str(installed), "check"]
    return ["uv", "run", "--project", str(config.code_standards_repo()), "code-standards", "check"]


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
    # Run from the target repository so language tools resolve its project
    # environment, while `--project` selects the code-standards CLI itself.
    result = _run(cmd, cwd=repo)
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


def check_governance() -> CheckResult:
    cmd = [sys.executable, "-m", "security_scan.governance", "verify"]
    env = {**os.environ, "PYTHONPATH": str(config.security_standards_src())}
    result = _run(cmd, cwd=config.security_standards_repo(), env=env)

    if result is None:
        return CheckResult("governance", UNKNOWN, note="governance verifier unavailable")

    if result.returncode == 0:
        return CheckResult("governance", PASS)

    if result.returncode == 1:
        details = []
        for line in result.stdout.splitlines():
            if line.strip():
                first_token = line.split()[0]
                details.append({"id": f"governance.{first_token}", "message": line})
        return CheckResult("governance", VIOLATION, details=details)

    stderr_lines = result.stderr.splitlines()
    first_line = stderr_lines[0] if stderr_lines else ""
    return CheckResult(
        "governance",
        UNKNOWN,
        note=f"governance verifier failed with rc {result.returncode}: {first_line}".rstrip(),
    )


_INFRA_REPORT_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


def _latest_infra_report(report_dir: Path) -> Path | None:
    if not report_dir.is_dir():
        return None
    candidates = [
        p for p in report_dir.iterdir() if p.is_file() and _INFRA_REPORT_NAME_RE.match(p.name)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.name)


def _infra_proposal_message(proposal: dict) -> str:
    return (
        proposal.get("description")
        or proposal.get("summary")
        or proposal.get("id")
        or "(no description)"
    )


def _infra_instance_unusable(inst) -> bool:
    # An instance is unusable if it isn't a dict, its audit didn't complete
    # (ok falsy), or its proposals field isn't a list — a malformed instance
    # must never read as clean.
    if not isinstance(inst, dict) or not inst.get("ok"):
        return True
    return not isinstance(inst.get("proposals", []), list)


def _all_infra_unknown(repo_resources: dict[str, list[str]], note: str) -> dict[str, CheckResult]:
    return {repo: CheckResult("infra", UNKNOWN, note=note) for repo in repo_resources}


def check_infra(  # noqa: C901
    repo_resources: dict[str, list[str]], now: datetime
) -> dict[str, CheckResult]:
    report_dir = config.infra_report_dir()
    report_path = _latest_infra_report(report_dir)
    if report_path is None:
        return _all_infra_unknown(repo_resources, "no infra drift report found")

    try:
        data = json.loads(report_path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _all_infra_unknown(repo_resources, "infra report unreadable")

    if not isinstance(data, dict) or "generated_at" not in data or "instances" not in data:
        return _all_infra_unknown(repo_resources, "infra report unreadable")

    instances = data["instances"]
    if not isinstance(instances, dict):
        return _all_infra_unknown(repo_resources, "infra report unreadable")

    try:
        generated_at = datetime.fromisoformat(str(data["generated_at"]).replace("Z", "+00:00"))
    except ValueError:
        return _all_infra_unknown(repo_resources, "infra report unreadable")

    # Judgment call: a naive datetime (now or generated_at) is treated as system-local time.
    now_aware = now.astimezone() if now.tzinfo is None else now
    age_hours = (now_aware.astimezone(UTC) - generated_at.astimezone(UTC)).total_seconds() / 3600
    if age_hours > config.infra_max_age_hours():
        return _all_infra_unknown(repo_resources, f"infra report stale: {report_path.name}")

    failed_instances = sorted(
        name for name, inst in instances.items() if _infra_instance_unusable(inst)
    )
    if failed_instances:
        return _all_infra_unknown(
            repo_resources, f"infra audit incomplete: {', '.join(failed_instances)} not ok"
        )

    all_proposals = []
    for inst in instances.values():
        all_proposals.extend(p for p in inst.get("proposals", []) if isinstance(p, dict))

    results = {}
    for repo, resources in repo_resources.items():
        if not resources:
            results[repo] = CheckResult(
                "infra",
                UNKNOWN,
                note="infra declared applicable but no coolify_resources in frontmatter",
            )
            continue

        matched = []
        for proposal in all_proposals:
            target = proposal.get("target")
            target = target if isinstance(target, dict) else {}
            if target.get("uuid") in resources or target.get("name") in resources:
                matched.append(proposal)

        if matched:
            details = [{"id": p.get("id"), "message": _infra_proposal_message(p)} for p in matched]
            results[repo] = CheckResult("infra", VIOLATION, details=details)
        else:
            results[repo] = CheckResult("infra", PASS, note=f"no drift found in {report_path.name}")

    return results
