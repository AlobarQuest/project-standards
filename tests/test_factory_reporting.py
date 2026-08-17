"""The nightly Q2 sweep and what it renders.

A check whose result is unreadable has the practical value of a check that
never ran, and this estate has demonstrated that twice: `PORTFOLIO.md` rendered
compliance as a bare symbol while `brain`'s real answer -- "pinned 1.0, current
1.1" -- sat in `portfolio.json`, and a predicted breakage went unnoticed for
four days with the data to catch it being written nightly. So the assertions
here are about the rendered page, not about the JSON.
"""

import json

from portfolio import config
from portfolio.matrix import NA, PASS, UNKNOWN, VIOLATION, CheckResult
from portfolio.scan import scan

FRONT = (
    "---\nname: {name}\ntier: active\nstatus: active\nversion: 1.0.0\n"
    "version_source: pyproject\npurpose: p\nupdated: 2026-08-17\n{extra}---\n\n## Backlog\n"
)


def _check(check_id, status, message="m", fix="do the thing"):
    return {
        "id": check_id,
        "status": status,
        "details": [{"id": f"{check_id}.detail", "message": message}],
        "fix": fix,
        "remediation": None,
    }


def _sweep(results):
    """A sweep stub keyed by repo NAME, resolved to whatever paths scan passes."""

    def sweep(repos):
        return {str(r): results[r.name] for r in repos if r.name in results}

    return sweep


def test_scan_attaches_factory_results_and_names_them_in_the_digest(make_repo, portfolio_env):
    repo = make_repo("declared", files={"PROJECT.md": FRONT.format(name="declared", extra="")})
    summary = scan(
        roots=[repo.parent],
        factory_sweep=_sweep(
            {
                "declared": [
                    _check("runner.caller", PASS),
                    _check(
                        "factory.pat_access",
                        VIOLATION,
                        "FACTORY_PR_TOKEN cannot reach AlobarQuest/declared",
                        "add it to the PAT's repository access list",
                    ),
                ]
            }
        ),
    )
    assert summary["factory_findings"] == 1
    data = json.loads(config.json_path().read_text())
    assert len(data["projects"][0]["factory"]) == 2

    digest = config.digest_path().read_text()
    assert "## Factory capability (Q2)" in digest
    # The check ID, the repository, and the detail message — not a symbol.
    assert "- factory.pat_access — declared" in digest
    assert "FACTORY_PR_TOKEN cannot reach AlobarQuest/declared" in digest
    assert "next: add it to the PAT's repository access list" in digest


def test_one_finding_shared_by_many_repos_is_rendered_once(make_repo, portfolio_env):
    """`factory.pat_scope` is `unknown` for every repository forever, so
    ungrouped it prints the same paragraph once per repo every night — the
    noise form of the bare-symbol problem this section exists to correct."""
    for name in ("a", "b", "c"):
        repo = make_repo(name, files={"PROJECT.md": FRONT.format(name=name, extra="")})
    shared = _check("factory.pat_scope", UNKNOWN, "not establishable read-only", "confirm it")
    scan(
        roots=[repo.parent],
        factory_sweep=_sweep({n: [dict(shared)] for n in ("a", "b", "c")}),
    )
    digest = config.digest_path().read_text()
    assert digest.count("not establishable read-only") == 1
    assert "- factory.pat_scope — a, b, c" in digest


def test_a_passing_capability_check_contributes_no_finding_line(make_repo, portfolio_env):
    repo = make_repo("declared", files={"PROJECT.md": FRONT.format(name="declared", extra="")})
    scan(roots=[repo.parent], factory_sweep=_sweep({"declared": [_check("runner.caller", PASS)]}))
    digest = config.digest_path().read_text()
    assert "## Factory capability (Q2)" in digest
    assert "### What failed" not in digest.split("## Factory capability (Q2)")[1]


def test_not_applicable_is_an_answer_and_never_a_finding(make_repo, portfolio_env):
    """ADR-0015 again, one layer out: a declared non-target and an out-of-scope
    repository are decisions. Counting them would put the noise the declaration
    exists to retire back into the nightly summary."""
    repo = make_repo("declared", files={"PROJECT.md": FRONT.format(name="declared", extra="")})
    summary = scan(
        roots=[repo.parent],
        factory_sweep=_sweep({"declared": [_check("runner.caller", NA), _check("x", PASS)]}),
    )
    assert summary["factory_findings"] == 0


def test_unknown_is_counted_as_a_finding(make_repo, portfolio_env):
    """An unmeasured capability is not a demonstrated one. The nightly run
    exists because Q2 lapses without the repository changing, so a sweep that
    could not see must not read as quiet."""
    repo = make_repo("declared", files={"PROJECT.md": FRONT.format(name="declared", extra="")})
    summary = scan(
        roots=[repo.parent],
        factory_sweep=_sweep({"declared": [_check("factory.pat_access", UNKNOWN)]}),
    )
    assert summary["factory_findings"] == 1


def test_repos_outside_q2_scope_do_not_appear_in_the_factory_section(make_repo, portfolio_env):
    repo = make_repo("plain", files={"PROJECT.md": FRONT.format(name="plain", extra="")})
    scan(roots=[repo.parent], factory_sweep=_sweep({}))
    digest = config.digest_path().read_text()
    assert "## Factory capability (Q2)" not in digest


def test_compliance_failures_are_named_not_just_symbolised(
    monkeypatch, make_repo, portfolio_env, standards_env
):
    """`brain`'s real answer reaching the page a human reads."""
    monkeypatch.setattr(
        "portfolio.compliance.checkers.check_project", lambda r: CheckResult("project", PASS)
    )
    repo = make_repo(
        "drifted",
        files={
            "PROJECT.md": (
                "---\nname: drifted\ntier: active\nstatus: active\nversion: 1.0\n"
                "version_source: none\npurpose: p\nupdated: '2026-08-17'\n"
                "applicable_standards:\n  project: '0.9'\n---\n\n## Backlog\n"
            )
        },
    )
    scan(roots=[repo.parent], factory_sweep=_sweep({}))
    digest = config.digest_path().read_text()
    assert "### What failed" in digest
    assert "drifted / project / project.version-drift: pinned 0.9, current 1.0" in digest


def test_an_unknown_compliance_cell_names_its_note(make_repo, portfolio_env):
    """An unknown cell carries a note rather than details; rendering only
    details would leave the commonest non-pass cell in the estate as a bare
    `?`."""
    repo = make_repo("bare")  # no PROJECT.md at all
    scan(roots=[repo.parent], factory_sweep=_sweep({}))
    digest = config.digest_path().read_text()
    assert "bare / project — no manifest" in digest
