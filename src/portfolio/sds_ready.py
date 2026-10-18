"""`portfolio sds-ready <repo>` -- is this repository ready for the SDS factory?

Runs the shared onboarding checks (measuring a repository with no declared
profile, since the caller named it), the SDS-specific checks, and the decisions
file; sorts the results by who acts on them; writes the build handoff and
Devon's task list under `~/.portfolio/onboarding/<repo>/`, and prints a summary
to stderr. Exit 0 = ready, 1 = not ready, 2 = the kit could not run, 3 = refused.

Read-only against GitHub, App Brain and the target repository; the same `.git/`
writes as `portfolio onboard` (see its module docstring).
"""

import json
import sys
from pathlib import Path

from . import onboard, onboard_checks
from .sds_assess import assess
from .sds_checks import (
    check_behavior_evidence,
    check_branch_settings,
    check_cred_inventory,
    check_declaration,
    check_landing_inert,
)
from .sds_decisions import check_decisions, onboarding_dir
from .sds_render import (
    HANDOFF_FILE,
    TASKS_FILE,
    RepoFacts,
    render_handoff,
    render_summary,
    render_tasks,
)

READINESS_FILE = "readiness.json"

# Manifest files whose presence tells a build agent what the repository is made of.
TOOLING_FILES = ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", "Dockerfile")


def run_all_checks(repo: Path, gh, gh_read, fetch=None) -> list[dict]:
    slug = onboard_checks.repo_slug(repo) or repo.name
    return [
        *onboard._run_checks(
            repo,
            gh,
            onboard_checks.registered_profiles(),
            gh_read,
            measure_unscoped=True,
        ),
        check_decisions(repo.name),
        check_declaration(slug, gh_read=gh_read),
        check_cred_inventory(slug, gh_read=gh_read),
        check_branch_settings(slug, gh_read=gh_read),
        check_behavior_evidence(slug, gh_read=gh_read),
        check_landing_inert(slug, fetch=fetch),
    ]


def _default_branch(slug: str, gh_read) -> str:
    out, _ = gh_read(["api", f"repos/{slug}"])
    try:
        branch = json.loads(out)["default_branch"] if out else None
    except ValueError, KeyError, TypeError:
        return "unknown"
    return branch if isinstance(branch, str) and branch else "unknown"


def _sync(path: Path, text: str) -> None:
    """Write `text`, or delete the file when there is nothing to say."""
    if text:
        path.write_text(text)
    else:
        path.unlink(missing_ok=True)


def run(repo: Path, gh=onboard_checks._gh, gh_read=onboard_checks._gh_read) -> int:
    if not repo.is_dir():
        print(f"sds-ready: not a directory: {repo}", file=sys.stderr)
        return 2
    repo = repo.resolve()
    slug = onboard_checks.repo_slug(repo)
    if slug is None:
        print(f"sds-ready: {repo} has no GitHub origin remote", file=sys.stderr)
        return 2
    try:
        checks = run_all_checks(repo, gh, gh_read)
        verdict = assess(checks)
        facts = RepoFacts(
            name=repo.name,
            slug=slug,
            default_branch=_default_branch(slug, gh_read),
            tooling=tuple(f for f in TOOLING_FILES if (repo / f).exists()),
            checkout=repo,
        )
        handoff = render_handoff(facts, verdict) if verdict.repository else ""
        tasks = render_tasks(facts, verdict) if verdict.devon else ""
        summary = render_summary(facts, verdict)
        out_dir = onboarding_dir(repo.name)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / READINESS_FILE).write_text(json.dumps(checks, indent=2) + "\n")
        _sync(out_dir / HANDOFF_FILE, handoff)
        _sync(out_dir / TASKS_FILE, tasks)
    except Exception as error:  # kit bug or unwritable output: never a partial verdict
        print(f"sds-ready: internal error: {error}", file=sys.stderr)
        return 2
    print(summary, file=sys.stderr)
    if verdict.refusals:
        return 3
    return 0 if verdict.ready else 1
