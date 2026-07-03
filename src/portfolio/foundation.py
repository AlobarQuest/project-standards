import json
from datetime import datetime

from . import checkers, compliance, config, exceptions
from .aggregate import _iter_repos
from .manifest import read_manifest
from .matrix import MACHINE, build_report, render_digest, resolve_cell, summarize


class FoundationError(Exception): ...


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

    machine_exc = exceptions.load(config.exceptions_path())

    repos = sorted(foundational_repos(roots), key=lambda pair: pair[0].name)
    if not repos:
        raise FoundationError("no foundational repos found under roots")

    rows, stale_repo_exceptions = compliance.build_rows(repos, now, now.date())

    governance_result = checkers.check_governance()
    machine_cell, used = resolve_cell(governance_result, machine_exc, MACHINE)
    unused_exceptions = [entry for idx, entry in enumerate(machine_exc)
                         if idx not in used]

    summary = summarize(rows, machine_cell)
    generated = now.isoformat(timespec="seconds")
    report = build_report(rows, machine_cell, summary, unused_exceptions, generated)
    report["stale_repo_exceptions"] = stale_repo_exceptions
    digest = render_digest(rows, machine_cell, summary, unused_exceptions, generated,
                           stale_repo_exceptions)

    home = config.portfolio_home()
    home.mkdir(parents=True, exist_ok=True)
    config.foundation_json_path().write_text(json.dumps(report, indent=2))
    config.foundation_digest_path().write_text(digest)

    return report
