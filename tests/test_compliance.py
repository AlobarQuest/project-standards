from datetime import date, datetime
from pathlib import Path

import pytest

from portfolio import compliance
from portfolio.matrix import ACCEPTED, NA, PASS, UNKNOWN, VIOLATION, CheckResult

NOW = datetime(2026, 7, 3, 12, 0, 0)
TODAY = date(2026, 7, 3)


@pytest.fixture
def quiet_checkers(monkeypatch):
    """All real checkers pass; no subprocesses. Records which repos ran."""
    ran = []

    def _mk(std):
        def check(repo):
            ran.append((std, Path(repo).name))
            return CheckResult(std, PASS)

        return check

    monkeypatch.setattr(compliance.checkers, "check_project", _mk("project"))
    monkeypatch.setattr(compliance.checkers, "check_security", _mk("security"))
    monkeypatch.setattr(compliance.checkers, "check_code", _mk("code"))
    monkeypatch.setattr(
        compliance.checkers,
        "check_infra",
        lambda resources, now: {name: CheckResult("infra", PASS) for name in resources},
    )
    return ran


def _fm(**over):
    base = {"applicable_standards": {"project": "1.0"}}
    return {**base, **over}


def test_no_manifest_row_is_all_unknown(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "bare"
    repo.mkdir()
    rows, stale = compliance.build_rows([(repo, None)], NOW, TODAY)
    assert all(
        c.status == UNKNOWN and c.note == compliance.NO_MANIFEST_NOTE
        for c in rows[0].cells.values()
    )
    assert quiet_checkers == []  # no checkers ran


def test_yaml_error_row_is_all_unknown(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "broken"
    repo.mkdir()
    rows, _ = compliance.build_rows([(repo, {"_yaml_error": "boom"})], NOW, TODAY)
    assert all(
        c.status == UNKNOWN and c.note == compliance.UNREADABLE_NOTE for c in rows[0].cells.values()
    )
    assert quiet_checkers == []


def test_undeclared_row_is_all_unknown_without_checkers(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "plain"
    repo.mkdir()
    rows, _ = compliance.build_rows([(repo, {"name": "plain"})], NOW, TODAY)
    assert all(
        c.status == UNKNOWN and c.note == compliance.UNDECLARED_NOTE for c in rows[0].cells.values()
    )
    assert quiet_checkers == []


def test_declared_pinned_current_is_green(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "good"
    repo.mkdir()
    fm = _fm(required_checks=[], foundation=False)
    rows, _ = compliance.build_rows([(repo, fm)], NOW, TODAY)
    cells = rows[0].cells
    assert cells["project"].status == PASS
    assert cells["security"].status == "not-applicable"
    assert cells["checks"].status == NA  # non-foundation, none declared


def test_version_drift_is_violation(standards_env, quiet_checkers, tmp_path):
    (standards_env["project"] / "STANDARD_VERSION").write_text("1.1\n")
    repo = tmp_path / "drifty"
    repo.mkdir()
    rows, _ = compliance.build_rows([(repo, _fm())], NOW, TODAY)
    cell = rows[0].cells["project"]
    assert cell.status == VIOLATION
    assert any(
        d["id"] == "project.version-drift" and "1.0" in d["message"] and "1.1" in d["message"]
        for d in cell.details
    )


def test_unpinned_is_violation_when_current_known(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "listform"
    repo.mkdir()
    rows, _ = compliance.build_rows([(repo, {"applicable_standards": ["project"]})], NOW, TODAY)
    cell = rows[0].cells["project"]
    assert cell.status == VIOLATION
    assert any(d["id"] == "project.version-unpinned" for d in cell.details)


def test_missing_standard_version_file_notes_not_drifts(standards_env, quiet_checkers, tmp_path):
    (standards_env["project"] / "STANDARD_VERSION").unlink()
    repo = tmp_path / "nofile"
    repo.mkdir()
    rows, _ = compliance.build_rows([(repo, _fm())], NOW, TODAY)
    cell = rows[0].cells["project"]
    assert cell.status == PASS
    assert "version unknown" in (cell.note or "")


def test_infra_null_pin_is_not_a_finding(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "infra"
    repo.mkdir()
    fm = {"applicable_standards": {"infra": None}, "coolify_resources": ["u1"]}
    rows, _ = compliance.build_rows([(repo, fm)], NOW, TODAY)
    assert rows[0].cells["infra"].status == PASS


def test_exception_masks_and_stale_reported(standards_env, quiet_checkers, monkeypatch, tmp_path):
    monkeypatch.setattr(
        compliance.checkers,
        "check_code",
        lambda repo: CheckResult(
            "code", VIOLATION, details=[{"id": "code.not-onboarded", "message": "m"}]
        ),
    )
    repo = tmp_path / "excused"
    repo.mkdir()
    fm = {
        "applicable_standards": {"code": "1.0"},
        "exceptions": [
            {
                "standard": "code",
                "finding": "code.not-onboarded",
                "reason": "wave 2",
                "added": "2026-07-03",
            },
            {
                "standard": "security",
                "finding": "security.*",
                "reason": "stale",
                "added": "2026-07-03",
            },
        ],
    }
    rows, stale = compliance.build_rows([(repo, fm)], NOW, TODAY)
    assert rows[0].cells["code"].status == ACCEPTED
    assert [e["reason"] for e in stale[str(repo.resolve())]] == ["stale"]


def test_fatal_contract_marker_all_unknown(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "future"
    repo.mkdir()
    rows, _ = compliance.build_rows(
        [(repo, {"foundation_contract": 9, "applicable_standards": {"project": "1.0"}})], NOW, TODAY
    )
    assert all(c.status == UNKNOWN for c in rows[0].cells.values())
    assert quiet_checkers == []


def test_foundation_checks_column_wired(standards_env, quiet_checkers, tmp_path, monkeypatch):
    repo = tmp_path / "found"
    repo.mkdir()
    wf = repo / ".github" / "workflows" / "quality.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("jobs:\n  quality: {}\n")
    fm = _fm(
        foundation=True,
        required_checks=[{"id": "quality", "executor": "github-actions:quality.yml"}],
    )
    rows, _ = compliance.build_rows([(repo, fm)], NOW, TODAY)
    assert rows[0].cells["checks"].status == PASS
    fm_none = _fm(foundation=True)
    rows, _ = compliance.build_rows([(repo, fm_none)], NOW, TODAY)
    assert any(d["id"] == "checks.none-declared" for d in rows[0].cells["checks"].details)
