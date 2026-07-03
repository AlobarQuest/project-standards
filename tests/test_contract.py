from pathlib import Path

from portfolio.contract import (
    Contract, parse_contract, current_standard_versions, CONTRACT_VERSION,
)


def test_list_form_is_declared_but_unpinned():
    c = parse_contract({"applicable_standards": ["project", "code"]})
    assert c.declared and c.fatal is None
    assert c.standards == {"project": None, "code": None}


def test_map_form_with_pins_and_null():
    c = parse_contract({"applicable_standards": {"project": "1.0", "infra": None}})
    assert c.declared
    assert c.standards == {"project": "1.0", "infra": None}


def test_missing_or_empty_is_undeclared():
    assert parse_contract({}).declared is False
    assert parse_contract({"applicable_standards": []}).declared is False
    assert parse_contract({"applicable_standards": {}}).declared is False


def test_unknown_standard_key_is_error():
    c = parse_contract({"applicable_standards": {"projct": "1.0"}})
    assert not c.declared
    assert any("projct" in e for e in c.errors)


def test_bad_types_are_errors_not_crashes():
    c = parse_contract({"applicable_standards": "project"})
    assert not c.declared and c.errors
    c = parse_contract({"applicable_standards": {"project": 1.0}})
    assert not c.declared and c.errors


def test_future_contract_marker_is_fatal():
    c = parse_contract({"foundation_contract": 2,
                        "applicable_standards": {"project": "1.0"}})
    assert c.fatal is not None
    assert not c.declared


def test_contract_marker_1_is_accepted():
    c = parse_contract({"foundation_contract": 1,
                        "applicable_standards": {"project": "1.0"}})
    assert c.fatal is None and c.declared


def test_required_checks_passthrough():
    entries = [{"id": "quality", "executor": "github-actions:quality.yml"}]
    c = parse_contract({"applicable_standards": {"project": "1.0"},
                        "required_checks": entries})
    assert c.required_checks == entries


def test_required_checks_non_list_is_error():
    c = parse_contract({"applicable_standards": {"project": "1.0"},
                        "required_checks": "quality"})
    assert c.required_checks == [] and c.errors


def test_current_versions_reads_files(monkeypatch, tmp_path):
    for std in ("project", "code", "security"):
        repo = tmp_path / std
        repo.mkdir()
    (tmp_path / "project" / "STANDARD_VERSION").write_text("1.0\n")
    (tmp_path / "code" / "STANDARD_VERSION").write_text("2.1\n")
    # security: no file -> None
    monkeypatch.setenv("PROJECT_STANDARDS_REPO", str(tmp_path / "project"))
    monkeypatch.setenv("CODE_STANDARDS_REPO", str(tmp_path / "code"))
    monkeypatch.setenv("SECURITY_STANDARDS_REPO", str(tmp_path / "security"))
    assert current_standard_versions() == {"project": "1.0", "code": "2.1",
                                           "security": None}
