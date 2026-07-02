import json

from portfolio import matrix
from portfolio.matrix import (
    CheckResult, Cell, Row,
    PASS, VIOLATION, ACCEPTED, NA, UNKNOWN,
    na_cell, resolve_cell, summarize, build_report, render_digest,
)


def exc(repo="repo1", standard="security", finding="42:*", reason="known issue"):
    return {"repo": repo, "standard": standard, "finding": finding, "reason": reason}


# --- na_cell ---

def test_na_cell():
    c = na_cell()
    assert c.status == NA
    assert c.details == []


# --- resolve_cell ---

def test_resolve_cell_pass_passes_through_unchanged():
    result = CheckResult(standard="security", status=PASS, details=[], note="all good")
    cell, used = resolve_cell(result, [], "repo1")
    assert cell.status == PASS
    assert cell.details == []
    assert cell.note == "all good"
    assert used == set()


def test_resolve_cell_unknown_preserves_note():
    result = CheckResult(standard="security", status=UNKNOWN, details=[], note="tool not run")
    cell, used = resolve_cell(result, [], "repo1")
    assert cell.status == UNKNOWN
    assert cell.note == "tool not run"
    assert used == set()


def test_resolve_cell_violation_fully_covered_by_one_glob_exception():
    result = CheckResult(standard="security", status=VIOLATION,
                          details=[{"id": "42:abc", "message": "bad thing"}])
    exceptions = [exc(repo="repo1", standard="security", finding="42:*", reason="glob covers it")]
    cell, used = resolve_cell(result, exceptions, "repo1")
    assert cell.status == ACCEPTED
    assert used == {0}
    assert cell.details[0]["accepted"] is True
    assert cell.details[0]["exception_reason"] == "glob covers it"


def test_resolve_cell_two_details_one_covered_stays_violation():
    result = CheckResult(standard="security", status=VIOLATION,
                          details=[{"id": "42:abc", "message": "bad thing"},
                                   {"id": "99:xyz", "message": "other thing"}])
    exceptions = [exc(repo="repo1", standard="security", finding="42:*", reason="covers 42 only")]
    cell, used = resolve_cell(result, exceptions, "repo1")
    assert cell.status == VIOLATION
    assert used == {0}
    covered = next(d for d in cell.details if d["id"] == "42:abc")
    uncovered = next(d for d in cell.details if d["id"] == "99:xyz")
    assert covered["accepted"] is True
    assert covered["exception_reason"] == "covers 42 only"
    assert "accepted" not in uncovered


def test_resolve_cell_no_exceptions_stays_violation_used_empty():
    result = CheckResult(standard="security", status=VIOLATION,
                          details=[{"id": "42:abc", "message": "bad thing"}])
    cell, used = resolve_cell(result, [], "repo1")
    assert cell.status == VIOLATION
    assert used == set()
    assert "accepted" not in cell.details[0]


def test_resolve_cell_exception_for_different_repo_does_not_match():
    result = CheckResult(standard="security", status=VIOLATION,
                          details=[{"id": "42:abc", "message": "bad thing"}])
    exceptions = [exc(repo="other-repo", standard="security", finding="42:*", reason="n/a")]
    cell, used = resolve_cell(result, exceptions, "repo1")
    assert cell.status == VIOLATION
    assert used == set()


def test_resolve_cell_violation_with_empty_details_stays_violation():
    result = CheckResult(standard="security", status=VIOLATION, details=[])
    cell, used = resolve_cell(result, [], "repo1")
    assert cell.status == VIOLATION
    assert used == set()


# --- summarize ---

def test_summarize_mixed_rows_and_machine_cell():
    rows = [
        Row(repo="a", path="/a", cells={
            "project": Cell(PASS),
            "security": Cell(VIOLATION, details=[{"id": "1", "message": "m"}]),
            "code": Cell(ACCEPTED, details=[{"id": "2", "message": "m", "accepted": True}]),
            "infra": Cell(NA),
        }),
        Row(repo="b", path="/b", cells={
            "project": Cell(PASS),
            "security": Cell(UNKNOWN, note="tool missing"),
            "code": Cell(PASS),
            "infra": Cell(VIOLATION, details=[{"id": "3", "message": "m"}]),
        }),
    ]
    machine_cell = Cell(PASS)
    summary = summarize(rows, machine_cell)
    assert summary == {
        PASS: 4,
        VIOLATION: 2,
        ACCEPTED: 1,
        NA: 1,
        UNKNOWN: 1,
    }


# --- build_report ---

def test_build_report_json_round_trips_and_exit_code():
    rows = [
        Row(repo="a", path="/a", cells={"project": Cell(VIOLATION, details=[{"id": "1", "message": "m"}])}),
    ]
    machine_cell = Cell(PASS)
    summary = {PASS: 1, VIOLATION: 1, ACCEPTED: 0, NA: 0, UNKNOWN: 0}
    unused = [exc(finding="stale:*")]
    report = build_report(rows, machine_cell, summary, unused, generated="2026-07-02T00:00:00Z")
    dumped = json.dumps(report)
    reloaded = json.loads(dumped)
    assert reloaded == report
    assert report["exit_code"] == 1
    assert report["generated"] == "2026-07-02T00:00:00Z"
    assert report["standards"] == matrix.STANDARDS
    assert report["repos"][0]["repo"] == "a"
    assert report["machine"]["governance"]["status"] == PASS
    assert report["unused_exceptions"] == unused


def test_build_report_exit_code_zero_when_no_violations():
    rows = [Row(repo="a", path="/a", cells={"project": Cell(PASS)})]
    machine_cell = Cell(PASS)
    summary = {PASS: 2, VIOLATION: 0, ACCEPTED: 0, NA: 0, UNKNOWN: 0}
    report = build_report(rows, machine_cell, summary, [], generated="2026-07-02T00:00:00Z")
    assert report["exit_code"] == 0


# --- render_digest ---

def _all_pass_rows():
    return [Row(repo="a", path="/a", cells={
        "project": Cell(PASS), "security": Cell(PASS), "code": Cell(PASS), "infra": Cell(NA),
    })]


def test_render_digest_all_pass_omits_violations_section():
    rows = _all_pass_rows()
    machine_cell = Cell(PASS)
    summary = {PASS: 4, VIOLATION: 0, ACCEPTED: 0, NA: 1, UNKNOWN: 0}
    out = render_digest(rows, machine_cell, summary, [], generated="2026-07-02T00:00:00Z")
    assert "# Foundation Conformance" in out
    assert "Generated: 2026-07-02T00:00:00Z" in out
    assert "repos: 1" in out
    assert "violations: 0" in out
    assert "unknown: 0" in out
    assert "## Violations" not in out
    assert "## Accepted exceptions in effect" not in out
    assert "## Unknown (work items, not failures)" not in out
    assert "## Stale exceptions (matched nothing — delete or fix)" not in out
    assert "—" in out  # NA symbol present in table


def test_render_digest_violation_row_and_section():
    rows = [Row(repo="a", path="/a", cells={
        "project": Cell(PASS),
        "security": Cell(VIOLATION, details=[{"id": "42:abc", "message": "bad thing"}]),
        "code": Cell(PASS),
        "infra": Cell(NA),
    })]
    machine_cell = Cell(PASS)
    summary = {PASS: 3, VIOLATION: 1, ACCEPTED: 0, NA: 1, UNKNOWN: 0}
    out = render_digest(rows, machine_cell, summary, [], generated="2026-07-02T00:00:00Z")
    assert "❌" in out
    assert "## Violations" in out
    assert "### a / security" in out
    assert "- 42:abc: bad thing" in out


def test_render_digest_accepted_cell_symbol():
    rows = [Row(repo="a", path="/a", cells={
        "project": Cell(PASS),
        "security": Cell(ACCEPTED, details=[{"id": "42:abc", "message": "bad thing",
                                              "accepted": True, "exception_reason": "glob covers it"}]),
        "code": Cell(PASS),
        "infra": Cell(NA),
    })]
    machine_cell = Cell(PASS)
    summary = {PASS: 3, VIOLATION: 0, ACCEPTED: 1, NA: 1, UNKNOWN: 0}
    out = render_digest(rows, machine_cell, summary, [], generated="2026-07-02T00:00:00Z")
    assert "⚠ accepted" in out
    assert "## Accepted exceptions in effect" in out
    assert "- a / security / 42:abc — glob covers it" in out
    assert "## Violations" not in out


def test_render_digest_unknown_cell_and_section():
    rows = [Row(repo="a", path="/a", cells={
        "project": Cell(PASS),
        "security": Cell(UNKNOWN, note="tool not run"),
        "code": Cell(PASS),
        "infra": Cell(NA),
    })]
    machine_cell = Cell(PASS)
    summary = {PASS: 3, VIOLATION: 0, ACCEPTED: 0, NA: 1, UNKNOWN: 1}
    out = render_digest(rows, machine_cell, summary, [], generated="2026-07-02T00:00:00Z")
    assert "?" in out
    assert "## Unknown (work items, not failures)" in out
    assert "- a / security — tool not run" in out


def test_render_digest_stale_exceptions_section():
    rows = _all_pass_rows()
    machine_cell = Cell(PASS)
    summary = {PASS: 4, VIOLATION: 0, ACCEPTED: 0, NA: 1, UNKNOWN: 0}
    unused = [exc(repo="a", standard="security", finding="99:*", reason="never matched")]
    out = render_digest(rows, machine_cell, summary, unused, generated="2026-07-02T00:00:00Z")
    assert "## Stale exceptions (matched nothing — delete or fix)" in out
    assert "- a / security / 99:* — never matched" in out


def test_render_digest_machine_scope_line():
    rows = _all_pass_rows()
    machine_cell = Cell(VIOLATION, details=[{"id": "gov:1", "message": "bad governance"}])
    summary = {PASS: 4, VIOLATION: 1, ACCEPTED: 0, NA: 1, UNKNOWN: 0}
    out = render_digest(rows, machine_cell, summary, [], generated="2026-07-02T00:00:00Z")
    assert "Machine scope: governance = ❌" in out
    assert "### _machine / governance" in out
    assert "- gov:1: bad governance" in out
