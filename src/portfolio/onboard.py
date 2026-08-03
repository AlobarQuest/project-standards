"""`portfolio onboard <repo>` — one-command repo readiness (WS-P2.11).

Runs the admission + advisory check set against ONE repo and emits the
portfolio-readiness/v1 document: JSON to stdout, a human digest (next action
named for every failure) to stderr, and a copy under
~/.portfolio/readiness/<name>.json. Exit 0 = admission passed, 1 = admission
failed, 2 = the kit itself could not run. Read-only against the target repo
and GitHub settings by design (Q5).
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from . import config, onboard_checks
from .checkers import check_project
from .matrix import PASS
from .readiness_schema import ADMISSION_CHECKS, ADVISORY_CHECKS, build_result


def _project_manifest_check(repo: Path) -> dict:
    base = check_project(repo)
    if base.status == PASS:
        return {
            "id": "project.manifest",
            "status": "pass",
            "details": base.details,
            "fix": None,
            "remediation": None,
        }
    return {
        "id": "project.manifest",
        "status": base.status,
        "details": base.details,
        "fix": f"portfolio lint {repo} and fix every FAIL (portfolio init scaffolds a manifest)",
        "remediation": {"summary": "make PROJECT.md a valid portfolio manifest"},
    }


def _run_checks(
    repo: Path, gh, registered: list[str] | None, gh_read=onboard_checks._gh_read
) -> list[dict]:
    slug = onboard_checks.repo_slug(repo) or repo.name
    return [
        onboard_checks.check_git_current(repo),
        _project_manifest_check(repo),
        onboard_checks.check_code_onboarded(repo),
        onboard_checks.check_ci_executed(repo, gh=gh),
        onboard_checks.check_security_clean(repo),
        onboard_checks.check_runner_caller(repo, slug, gh=gh),
        onboard_checks.check_profile_declared(repo, registered_profiles=registered),
        onboard_checks.check_dependabot(repo),
        onboard_checks.check_protection(slug, gh_read=gh_read),
        onboard_checks.check_backlog_hygiene(repo),
        onboard_checks.check_standards_pinned(repo),
    ]


def _digest(document: dict) -> str:
    lines = [f"readiness: {document['repo']} — admission "]
    lines[0] += "PASSED" if document["admission_passed"] else "FAILED"
    by_kind = {"admission": ADMISSION_CHECKS, "advisory": ADVISORY_CHECKS}
    for kind, ids in by_kind.items():
        for check in document["checks"]:
            if check["id"] not in ids:
                continue
            mark = "ok" if check["status"] == "pass" else check["status"].upper()
            line = f"  [{mark}] {check['id']} ({kind})"
            if check["status"] != "pass" and check["fix"]:
                line += f"\n        next: {check['fix']}"
            lines.append(line)
    lines.append(
        "  certification: not attempted — a docs-only canary through the factory is the"
        " separate final step (checks-pass != certified)"
    )
    return "\n".join(lines)


def run(repo: Path, gh=onboard_checks._gh, gh_read=onboard_checks._gh_read) -> int:
    if not repo.is_dir():
        print(f"onboard: not a directory: {repo}", file=sys.stderr)
        return 2
    try:
        registered = onboard_checks.registered_profiles()
        checks = _run_checks(repo, gh, registered, gh_read)
        document = build_result(repo.name, checks, datetime.now(UTC))
    except Exception as error:  # kit bug: never masquerade as a readiness verdict
        print(f"onboard: internal error: {error}", file=sys.stderr)
        return 2
    out_dir = config.portfolio_home() / "readiness"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{repo.name}.json").write_text(json.dumps(document, indent=2) + "\n")
    print(json.dumps(document, indent=2))
    print(_digest(document), file=sys.stderr)
    return 0 if document["admission_passed"] else 1
