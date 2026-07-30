import json

import pytest

from portfolio import onboard
from portfolio.cli import main
from portfolio.readiness_schema import ADMISSION_CHECKS, ADVISORY_CHECKS


def _pass(check_id):
    return {"id": check_id, "status": "pass", "details": [], "fix": None, "remediation": None}


@pytest.fixture
def all_green(monkeypatch):
    def fake_run_checks(repo, gh, registered):
        return [_pass(c) for c in ADMISSION_CHECKS + ADVISORY_CHECKS]

    monkeypatch.setattr(onboard, "_run_checks", fake_run_checks)


def test_onboard_green_exit_zero_writes_result(portfolio_env, make_repo, all_green, capsys):
    repo = make_repo("greenrepo")
    rc = main(["onboard", str(repo)])
    assert rc == 0
    out, err = capsys.readouterr()
    document = json.loads(out)
    assert document["schema"] == "portfolio-readiness/v1"
    assert document["admission_passed"] is True
    assert document["certified"] is False
    assert "certification" in err  # digest names the gated step
    on_disk = portfolio_env / "readiness" / "greenrepo.json"
    assert json.loads(on_disk.read_text()) == document


def test_onboard_admission_failure_exit_one_digest_names_fix(
    portfolio_env, make_repo, monkeypatch, capsys
):
    def fake_run_checks(repo, gh, registered):
        checks = [_pass(c) for c in ADMISSION_CHECKS + ADVISORY_CHECKS]
        checks[0] = {
            "id": ADMISSION_CHECKS[0],
            "status": "violation",
            "details": [{"id": "x", "message": "m"}],
            "fix": "run the exact fix command",
            "remediation": {"summary": "s"},
        }
        return checks

    monkeypatch.setattr(onboard, "_run_checks", fake_run_checks)
    repo = make_repo("gappy")
    rc = main(["onboard", str(repo)])
    assert rc == 1
    out, err = capsys.readouterr()
    document = json.loads(out)
    assert document["admission_passed"] is False
    assert len(document["remediation_queue"]) == 1
    assert "run the exact fix command" in err


def test_onboard_missing_repo_exit_two(portfolio_env, tmp_path, capsys):
    rc = main(["onboard", str(tmp_path / "nope")])
    assert rc == 2


def test_onboard_internal_error_exit_two(portfolio_env, make_repo, monkeypatch, capsys):
    def boom(repo, gh, registered):
        raise RuntimeError("kit bug")

    monkeypatch.setattr(onboard, "_run_checks", boom)
    rc = main(["onboard", str(make_repo("x"))])
    assert rc == 2
