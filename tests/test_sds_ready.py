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
    return portfolio_env / "onboarding" / "AlobarQuest__widget"


def test_run_all_checks_measures_the_named_repository(repo, portfolio_env, monkeypatch):
    """A named repository is measured whatever it declares: scope is the nightly sweep's
    question, answered from the member record, and never this command's."""
    from portfolio.factory_checks import FACTORY_CHECKS

    monkeypatch.setattr(onboard_checks, "registered_profiles", lambda: None)
    monkeypatch.setattr(onboard_checks, "check_git_current", lambda repo: _check("git.current"))
    monkeypatch.setattr(
        onboard_checks, "check_security_clean", lambda repo: _check("security.clean")
    )
    for var in (config.FACTORY_PAT_ENV, config.APP_BRAIN_KEY_ENV, config.DISPATCH_APP_KEY_ENV):
        monkeypatch.delenv(var, raising=False)
    checks = sds_ready.run_all_checks(repo, _gh, _gh_read, fetch=lambda slug: {"landing": "inert"})
    factory = [c for c in checks if c["id"] in FACTORY_CHECKS]
    assert [c["id"] for c in factory] == list(FACTORY_CHECKS)
    assert all(c["status"] != "not-applicable" for c in factory)


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


def test_unwritable_output_exits_2(repo, portfolio_env, monkeypatch, capsys):
    (portfolio_env / "onboarding").write_text("a file where the directory belongs")
    _install(monkeypatch, _with(_all_pass(), "code.onboarded", "violation"))
    assert sds_ready.run(repo, gh=_gh, gh_read=_gh_read) == 2
    assert "sds-ready: internal error" in capsys.readouterr().err


def test_refusal_with_repository_work_still_writes_the_handoff(repo, portfolio_env, monkeypatch):
    checks = _with(_all_pass(), "code.onboarded", "violation")
    checks = _with(
        checks,
        "sds.landing_inert",
        "violation",
        [{"id": "sds.refused-redeploys", "message": "landing redeploys"}],
    )
    _install(monkeypatch, checks)
    assert sds_ready.run(repo, gh=_gh, gh_read=_gh_read) == 3
    assert "code.onboarded" in (_home(portfolio_env) / HANDOFF_FILE).read_text()


def test_decisions_are_keyed_on_the_slug_not_the_folder(repo, portfolio_env, monkeypatch):
    seen = []
    monkeypatch.setattr(
        sds_ready, "check_decisions", lambda key: seen.append(key) or _check("sds.decisions")
    )
    monkeypatch.setattr(onboard_checks, "registered_profiles", lambda: None)
    monkeypatch.setattr(onboard_checks, "check_git_current", lambda repo: _check("git.current"))
    monkeypatch.setattr(
        onboard_checks, "check_security_clean", lambda repo: _check("security.clean")
    )
    sds_ready.run_all_checks(repo, _gh, _gh_read, fetch=lambda slug: {"landing": "inert"})
    assert seen == ["AlobarQuest__widget"]


def test_onboard_measures_factory_checks_on_a_repository_declaring_no_profile(repo, monkeypatch):
    """`portfolio onboard` measures the repository it is named. A `delivery_profile` once
    decided whether these rows were measured; the member record decides the nightly sweep's
    scope now, and a named repository is in scope by being named. Capability rows never
    touch admission or the remediation queue, so measuring them changes only the report."""
    monkeypatch.setattr(onboard_checks, "check_git_current", lambda repo: _check("git.current"))
    monkeypatch.setattr(
        onboard_checks, "check_security_clean", lambda repo: _check("security.clean")
    )
    for var in (config.FACTORY_PAT_ENV, config.APP_BRAIN_KEY_ENV, config.DISPATCH_APP_KEY_ENV):
        monkeypatch.delenv(var, raising=False)
    checks = sds_ready.onboard._run_checks(repo, _gh, None, _gh_read)
    factory = [c for c in checks if c["id"].startswith("factory.")]
    assert factory
    assert "not-applicable" not in {c["status"] for c in factory}


def test_onboard_reports_unknown_factory_checks_for_a_repository_with_no_origin(
    make_repo, monkeypatch
):
    """With no origin there is no repository to probe: never a bare directory name."""
    from portfolio.factory_checks import FACTORY_CHECKS

    bare = make_repo("bare-dir", files={"pyproject.toml": ""})
    monkeypatch.setattr(onboard_checks, "check_git_current", lambda repo: _check("git.current"))
    monkeypatch.setattr(
        onboard_checks, "check_security_clean", lambda repo: _check("security.clean")
    )
    monkeypatch.setenv(config.FACTORY_PAT_ENV, "test-pat-value")
    monkeypatch.setattr(
        "portfolio.factory_checks._token_gh_read",
        lambda _token: pytest.fail("a bare directory name must not reach GitHub"),
    )
    checks = sds_ready.onboard._run_checks(bare, _gh, None, _gh_read)
    factory = {c["id"]: c for c in checks if c["id"] in FACTORY_CHECKS}
    assert set(factory) == set(FACTORY_CHECKS)
    assert {c["status"] for c in factory.values()} == {"unknown"}
    assert factory["factory.pat_access"]["details"][0]["id"] == "factory.pat_access.no-origin"
