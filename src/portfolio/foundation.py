import json
from datetime import datetime

from . import checkers, config, exceptions
from .aggregate import _iter_repos
from .manifest import read_manifest
from .matrix import (
    MACHINE, STANDARDS,
    Row, build_report, na_cell, render_digest, resolve_cell, summarize,
)


class FoundationError(Exception): ...


_PER_REPO_CHECKERS = {
    "project": lambda repo: checkers.check_project(repo),
    "security": lambda repo: checkers.check_security(repo),
    "code": lambda repo: checkers.check_code(repo),
}


def foundational_repos(roots):
    for repo in _iter_repos(roots):
        m = read_manifest(repo)
        if m is None:
            continue
        fm = m.frontmatter
        if "_yaml_error" in fm:
            continue
        if fm.get("foundation") is True:
            yield repo, fm


def run_foundation(roots=None, now=None) -> dict:
    roots = roots or config.DEFAULT_ROOTS
    now = now or datetime.now()

    exc = exceptions.load(config.exceptions_path())

    repos = sorted(foundational_repos(roots), key=lambda pair: pair[0].name)
    if not repos:
        raise FoundationError("no foundational repos found under roots")

    used_indices: set[int] = set()
    rows_by_repo: dict[str, Row] = {}

    for repo, fm in repos:
        applicable = fm.get("applicable_standards") or []
        cells = {}
        for std in STANDARDS:
            if std not in applicable:
                cells[std] = na_cell()
                continue
            if std == "infra":
                continue  # resolved in the batch pass below
            result = _PER_REPO_CHECKERS[std](repo)
            cell, used = resolve_cell(result, exc, repo.name)
            cells[std] = cell
            used_indices |= used
        rows_by_repo[repo.name] = Row(repo=repo.name, path=str(repo), cells=cells)

    repo_resources = {
        repo.name: fm.get("coolify_resources") or []
        for repo, fm in repos
        if "infra" in (fm.get("applicable_standards") or [])
    }
    infra_results = checkers.check_infra(repo_resources, now)
    for repo_name, result in infra_results.items():
        cell, used = resolve_cell(result, exc, repo_name)
        rows_by_repo[repo_name].cells["infra"] = cell
        used_indices |= used

    governance_result = checkers.check_governance()
    machine_cell, used = resolve_cell(governance_result, exc, MACHINE)
    used_indices |= used

    unused_exceptions = [entry for idx, entry in enumerate(exc) if idx not in used_indices]

    rows = [rows_by_repo[repo.name] for repo, _fm in repos]
    summary = summarize(rows, machine_cell)
    generated = now.isoformat(timespec="seconds")
    report = build_report(rows, machine_cell, summary, unused_exceptions, generated)
    digest = render_digest(rows, machine_cell, summary, unused_exceptions, generated)

    home = config.portfolio_home()
    home.mkdir(parents=True, exist_ok=True)
    config.foundation_json_path().write_text(json.dumps(report, indent=2))
    config.foundation_digest_path().write_text(digest)

    return report
