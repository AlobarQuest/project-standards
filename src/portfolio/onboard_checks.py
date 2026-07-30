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
