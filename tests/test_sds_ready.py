import json
import subprocess

import pytest

from portfolio import cli, config, onboard_checks, sds_ready
from portfolio.cli import main
from portfolio.sds_guidance import EXCLUDED, GUIDANCE
from portfolio.sds_render import HANDOFF_FILE, TASKS_FILE


def _check(check_id, status="pass", details=None):
    return {
        "id": check_id,
        "status": status,
        "details": details or [],
        "fix": None,
        "remediation": None,
    }


def _all_pass():
    return [_check(check_id) for check_id in (*GUIDANCE, *EXCLUDED)]


def _with(checks, check_id, status, details=None):
    return [_check(check_id, status, details) if c["id"] == check_id else c for c in checks]


@pytest.fixture
def repo(make_repo):
    repo = make_repo("widget", files={"pyproject.toml": "", "package.json": "{}"})
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/AlobarQuest/widget.git"],
        cwd=repo,
        check=True,
    )
    return repo


def _gh_read(args):
    if args == ["api", "repos/AlobarQuest/widget"]:
        return json.dumps({"default_branch": "trunk"}), ""
    return None, "unreadable"


def _gh(args):
    return None


def _install(monkeypatch, checks):
    monkeypatch.setattr(sds_ready, "run_all_checks", lambda *a, **k: checks)


def _home(portfolio_env):
    return portfolio_env / "onboarding" / "widget"


def test_run_all_checks_measures_unscoped_repositories(repo, portfolio_env, monkeypatch):
    seen = {}
    real = sds_ready.onboard._run_checks

    def spy(repo, gh, registered, gh_read=None, measure_unscoped=False):
        seen["measure_unscoped"] = measure_unscoped
        return real(repo, gh, registered, gh_read, measure_unscoped)

    monkeypatch.setattr(sds_ready.onboard, "_run_checks", spy)
    monkeypatch.setattr(onboard_checks, "registered_profiles", lambda: None)
    monkeypatch.setattr(
        onboard_checks, "check_security_clean", lambda repo: _check("security.clean")
    )
    for var in (config.FACTORY_PAT_ENV, config.APP_BRAIN_KEY_ENV, config.DISPATCH_APP_KEY_ENV):
        monkeypatch.delenv(var, raising=False)
    sds_ready.run_all_checks(repo, _gh, _gh_read, fetch=lambda slug: {"landing": "inert"})
    assert seen["measure_unscoped"] is True


def test_no_github_origin_exits_2_and_writes_nothing(make_repo, portfolio_env, monkeypatch, capsys):
    repo = make_repo("bare")
    _install(monkeypatch, _all_pass())
    assert sds_ready.run(repo, gh=_gh, gh_read=_gh_read) == 2
    assert "origin" in capsys.readouterr().err
    assert not (portfolio_env / "onboarding").exists()


def test_not_a_directory_exits_2(portfolio_env, tmp_path):
    assert sds_ready.run(tmp_path / "nope", gh=_gh, gh_read=_gh_read) == 2


def test_gaps_write_handoff_and_exit_1(repo, portfolio_env, monkeypatch, capsys):
    checks = _with(_all_pass(), "code.onboarded", "violation", [{"id": "x", "message": "m"}])
    _install(monkeypatch, checks)
    assert sds_ready.run(repo, gh=_gh, gh_read=_gh_read) == 1
    home = _home(portfolio_env)
    handoff = (home / HANDOFF_FILE).read_text()
    assert "code.onboarded" in handoff
    assert "trunk" in handoff
    assert not (home / TASKS_FILE).exists()
    assert [c["id"] for c in json.loads((home / "readiness.json").read_text())] == [
        c["id"] for c in checks
    ]
    assert "widget:" in capsys.readouterr().err


def test_devon_gaps_write_tasks(repo, portfolio_env, monkeypatch):
    _install(monkeypatch, _with(_all_pass(), "sds.decisions", "violation"))
    assert sds_ready.run(repo, gh=_gh, gh_read=_gh_read) == 1
    assert (_home(portfolio_env) / TASKS_FILE).is_file()
    assert not (_home(portfolio_env) / HANDOFF_FILE).exists()


def test_unreadable_default_branch_reads_unknown(repo, portfolio_env, monkeypatch):
    _install(monkeypatch, _with(_all_pass(), "code.onboarded", "violation"))
    assert sds_ready.run(repo, gh=_gh, gh_read=lambda args: (None, "no")) == 1
    assert "unknown" in (_home(portfolio_env) / HANDOFF_FILE).read_text()


def test_ready_removes_stale_files_and_exits_0(repo, portfolio_env, monkeypatch):
    home = _home(portfolio_env)
    home.mkdir(parents=True)
    (home / HANDOFF_FILE).write_text("stale")
    (home / TASKS_FILE).write_text("stale")
    _install(monkeypatch, _all_pass())
    assert sds_ready.run(repo, gh=_gh, gh_read=_gh_read) == 0
    assert not (home / HANDOFF_FILE).exists()
    assert not (home / TASKS_FILE).exists()
    assert (home / "readiness.json").is_file()


def test_redeploys_exits_3(repo, portfolio_env, monkeypatch, capsys):
    checks = _with(
        _all_pass(),
        "sds.landing_inert",
        "violation",
        [{"id": "sds.refused-redeploys", "message": "landing redeploys"}],
    )
    _install(monkeypatch, checks)
    assert sds_ready.run(repo, gh=_gh, gh_read=_gh_read) == 3
    assert "landing redeploys" in capsys.readouterr().err


def test_internal_error_exits_2_and_writes_nothing(repo, portfolio_env, monkeypatch, capsys):
    stale = _home(portfolio_env)
    stale.mkdir(parents=True)
    (stale / HANDOFF_FILE).write_text("keep")
    _install(monkeypatch, [*_all_pass(), _check("not.guided", "violation")])
    assert sds_ready.run(repo, gh=_gh, gh_read=_gh_read) == 2
    assert "sds-ready: internal error" in capsys.readouterr().err
    assert (stale / HANDOFF_FILE).read_text() == "keep"
    assert not (stale / "readiness.json").exists()


def test_cli_wires_sds_ready(repo, portfolio_env, monkeypatch):
    _install(monkeypatch, _all_pass())
    calls = []

    def fake_run(path):
        calls.append(path)
        return sds_ready.run(path, gh=_gh, gh_read=_gh_read)

    monkeypatch.setattr(cli, "sds_ready_run", fake_run)
    assert main(["sds-ready", str(repo)]) == 0
    assert calls == [repo]
