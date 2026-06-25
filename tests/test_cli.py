from portfolio.cli import main
from portfolio import config


def test_cli_scan_runs_and_writes(make_repo, portfolio_env, capsys):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: package.json\n"
            "purpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    assert main(["scan", "--roots", str(repo.parent)]) == 0
    assert config.json_path().exists() and "projects" in capsys.readouterr().out


def test_cli_lint_nonzero_on_fail(make_repo, portfolio_env):
    assert main(["lint", str(make_repo("x"))]) == 1     # no PROJECT.md → FAIL


def test_cli_add_accepts_multiword(make_repo, portfolio_env, monkeypatch):
    repo = make_repo("contacts", files={"package.json": '{"version":"1.0.0"}'})
    monkeypatch.chdir(repo)
    assert main(["add", "fix", "the", "login", "flow", "--repo", str(repo)]) == 0


def test_cli_triage_assign_without_repo_errors(portfolio_env):
    assert main(["triage", "--assign", "abc"]) == 2
