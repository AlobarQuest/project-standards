"""Per-repo onboarding checks (WS-P2.11).

Each check returns {id, status, details, fix, remediation}: `status` uses the
matrix vocabulary (pass/violation/unknown), `fix` names the exact next action,
and `remediation` (when not None) is the machine payload a failed ADMISSION
check contributes to the readiness result's remediation queue. Settings-only
fixes (Q5: the kit never writes GitHub settings) carry `fix` but no
`remediation`.

Remote reads go through the injectable `_gh` helper so tests construct failing
instances without the network; UNKNOWN is admission-failing by design — a
check that cannot see is never green.
"""

import json
import re
from pathlib import Path

from .checkers import _run
from .matrix import PASS, UNKNOWN, VIOLATION


def _gh(args: list[str]) -> str | None:
    """Run `gh` and return stdout, or None on any failure."""
    result = _run(["gh", *args])
    if result is None or result.returncode != 0:
        return None
    return result.stdout


def _result(check_id, status, details=None, fix=None, remediation=None):
    return {
        "id": check_id,
        "status": status,
        "details": details or [],
        "fix": fix,
        "remediation": remediation,
    }


def _git(repo: Path, *args: str):
    return _run(["git", "-C", str(repo), *args])


def repo_slug(repo: Path) -> str | None:
    """`owner/name` from the origin remote, or None."""
    result = _git(repo, "remote", "get-url", "origin")
    if result is None or result.returncode != 0:
        return None
    url = result.stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+/[^/\s]+?)(?:\.git)?$", url)
    return match.group(1) if match else None


def check_code_onboarded(repo: Path) -> dict:
    missing = []
    if not (repo / ".code-standards.toml").is_file():
        missing.append(
            {
                "id": "code.no-manifest",
                "message": ".code-standards.toml absent",
                "fix": f"cd {repo} && code-standards init",
            }
        )
    if not (repo / ".github/workflows/quality.yml").is_file():
        missing.append(
            {
                "id": "code.no-quality-workflow",
                "message": ".github/workflows/quality.yml absent",
                "fix": f"cd {repo} && code-standards sync",
            }
        )
    if missing:
        return _result(
            "code.onboarded",
            VIOLATION,
            details=[{"id": m["id"], "message": m["message"]} for m in missing],
            fix="; ".join(m["fix"] for m in missing),
            remediation={"summary": "onboard the repo to code-standards (init + sync)"},
        )
    return _result("code.onboarded", PASS)


_COLLECTED_RE = re.compile(r"collected (\d+) items?")


def check_ci_executed(repo: Path, gh=_gh) -> dict:
    """Latest quality run on main must have succeeded AND provably executed
    tests — `collected N items`, N > 0, read from the job log. Never the check
    color alone: the vendored CI can pass having run nothing (every tool
    command -v guarded, pytest exit 5 swallowed, no-lockfile repos install
    nothing)."""
    slug = repo_slug(repo)
    if slug is None:
        return _result(
            "ci.executed",
            UNKNOWN,
            details=[{"id": "ci.no-origin", "message": "cannot derive GitHub slug from origin"}],
            fix=f"add a GitHub origin remote to {repo}",
        )
    listing = gh(
        [
            "run",
            "list",
            "--repo",
            slug,
            "--workflow",
            "quality.yml",
            "--branch",
            "main",
            "--limit",
            "1",
            "--json",
            "databaseId,conclusion",
        ]
    )
    if listing is None:
        return _result(
            "ci.executed",
            UNKNOWN,
            details=[{"id": "ci.gh-failed", "message": "gh run list failed"}],
            fix="check gh auth and network, then re-run",
        )
    try:
        runs = json.loads(listing)
    except ValueError:
        runs = None
    if not runs:
        return _result(
            "ci.executed",
            UNKNOWN,
            details=[{"id": "ci.no-runs", "message": "no quality.yml runs on main"}],
            fix=f"push to main (or re-run the workflow) in {slug}, then re-run this check",
        )
    run = runs[0]
    if run.get("conclusion") != "success":
        return _result(
            "ci.executed",
            VIOLATION,
            details=[
                {
                    "id": "ci.not-green",
                    "message": f"latest quality run concluded {run.get('conclusion')!r}",
                }
            ],
            fix=f"fix the failing quality run on {slug} main",
            remediation={"summary": "make the quality workflow green on main"},
        )
    log = gh(["run", "view", str(run.get("databaseId")), "--repo", slug, "--log"])
    if log is None:
        return _result(
            "ci.executed",
            UNKNOWN,
            details=[{"id": "ci.log-unreadable", "message": "gh run view --log failed"}],
            fix="check gh auth and network, then re-run",
        )
    match = _COLLECTED_RE.search(log)
    if match is None or int(match.group(1)) == 0:
        found = "no 'collected N items' line" if match is None else "collected 0 items"
        return _result(
            "ci.executed",
            VIOLATION,
            details=[{"id": "ci.ran-nothing", "message": f"run succeeded but {found}"}],
            fix=(
                f"the green check on {slug} proves nothing ran: ensure pytest is installed by "
                "CI (dependency-groups, not optional-dependencies) and tests are collected — "
                "then verify the log shows 'collected N items' with N > 0"
            ),
            remediation={"summary": "make CI actually execute the test suite"},
        )
    return _result(
        "ci.executed",
        PASS,
        details=[{"id": "ci.collected", "message": f"collected {match.group(1)} items"}],
    )


def check_git_current(repo: Path) -> dict:
    fetch = _git(repo, "fetch", "--quiet", "origin", "main")
    if fetch is None or fetch.returncode != 0:
        message = "" if fetch is None else (fetch.stderr or fetch.stdout).strip()
        return _result(
            "git.current",
            VIOLATION,
            details=[{"id": "git.fetch-failed", "message": f"git fetch origin main: {message}"}],
            fix=f"ensure {repo} has an 'origin' remote on GitHub and network access, then re-run",
        )
    head = _git(repo, "rev-parse", "HEAD")
    remote = _git(repo, "rev-parse", "origin/main")
    if head is None or remote is None or head.returncode != 0 or remote.returncode != 0:
        return _result(
            "git.current",
            UNKNOWN,
            details=[
                {"id": "git.rev-parse-failed", "message": "could not resolve HEAD/origin/main"}
            ],
            fix=f"inspect {repo} by hand; rev-parse failed",
        )
    if head.stdout.strip() != remote.stdout.strip():
        return _result(
            "git.current",
            VIOLATION,
            details=[
                {
                    "id": "git.not-origin-main",
                    "message": (
                        f"HEAD {head.stdout.strip()[:12]} != origin/main "
                        f"{remote.stdout.strip()[:12]}"
                    ),
                }
            ],
            fix=f"git -C {repo} checkout main && git -C {repo} pull --ff-only origin main",
            remediation={"summary": "bring the checkout to current origin/main"},
        )
    status = _git(repo, "status", "--porcelain")
    if status is None or status.returncode != 0:
        return _result(
            "git.current",
            UNKNOWN,
            details=[{"id": "git.status-failed", "message": "git status failed"}],
            fix=f"inspect {repo} by hand",
        )
    if status.stdout.strip():
        return _result(
            "git.current",
            VIOLATION,
            details=[{"id": "git.dirty", "message": "worktree has uncommitted changes"}],
            fix=f"commit, stash, or discard the changes in {repo}, then re-run",
        )
    return _result("git.current", PASS)
