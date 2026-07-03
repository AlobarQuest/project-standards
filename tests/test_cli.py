from portfolio.cli import main
from portfolio import config
from portfolio.matrix import PASS, CheckResult


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


def test_cli_foundation_valid_repo_returns_zero(
        make_repo, portfolio_env, capsys, monkeypatch, standards_env):
    """Valid foundational repo with [project] only → returns 0, capsys contains 'foundation: 1 repos' and 'violations=0'."""
    # Monkeypatch check_governance to return PASS (cheaper than a real run)
    monkeypatch.setattr("portfolio.checkers.check_governance", lambda: CheckResult("governance", PASS))

    body = ("---\nname: foundational\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: package.json\n"
            "purpose: core infra\nupdated: 2026-06-25\nfoundation: true\n"
            "applicable_standards:\n  project: '1.0'\n"
            "required_checks:\n- id: quality\n  executor: github-actions:quality.yml\n"
            "---\n\n## Backlog\n")
    repo = make_repo("foundational", files={"PROJECT.md": body})
    wf = repo / ".github" / "workflows" / "quality.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("jobs:\n  quality: {}\n")

    assert main(["foundation", "--roots", str(repo.parent)]) == 0
    out = capsys.readouterr().out
    assert "foundation: 1 repos" in out
    assert "violations=0" in out


def test_cli_foundation_broken_manifest_returns_one(
        make_repo, portfolio_env, capsys, monkeypatch, standards_env):
    """Broken manifest (missing required fields) → returns 1, output contains 'violations=1'."""
    monkeypatch.setattr("portfolio.checkers.check_governance", lambda: CheckResult("governance", PASS))

    # Missing required fields for active tier (status, version, version_source)
    body = ("---\nname: broken\ntier: active\npurpose: broken\nupdated: 2026-06-25\nfoundation: true\n"
            "applicable_standards:\n  project: '1.0'\n"
            "required_checks:\n- id: quality\n  executor: github-actions:quality.yml\n"
            "---\n\n## Backlog\n")
    repo = make_repo("broken", files={"PROJECT.md": body})
    wf = repo / ".github" / "workflows" / "quality.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("jobs:\n  quality: {}\n")

    assert main(["foundation", "--roots", str(repo.parent)]) == 1
    out = capsys.readouterr().out
    assert "violations=1" in out


def test_cli_foundation_malformed_exceptions_toml_returns_two(make_repo, portfolio_env, capsys, monkeypatch, tmp_path):
    """Malformed FOUNDATION_EXCEPTIONS TOML → returns 2, output starts with 'error:'."""
    monkeypatch.setattr("portfolio.checkers.check_governance", lambda: CheckResult("governance", PASS))

    # Create a malformed TOML file and set it as the exceptions path
    exceptions_file = tmp_path / "bad.toml"
    exceptions_file.write_text("this is not [valid toml")
    monkeypatch.setenv("FOUNDATION_EXCEPTIONS", str(exceptions_file))

    body = ("---\nname: foundational\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: package.json\n"
            "purpose: core\nupdated: 2026-06-25\nfoundation: true\napplicable_standards: [project]\n---\n\n## Backlog\n")
    repo = make_repo("foundational", files={"PROJECT.md": body})

    assert main(["foundation", "--roots", str(repo.parent)]) == 2
    out = capsys.readouterr().out
    assert out.startswith("error:")


def test_cli_foundation_no_foundational_repos_returns_two(portfolio_env, capsys):
    """No foundational repos under roots → returns 2, output contains 'error: no foundational repos'."""
    # Create an empty root (no repos)
    assert main(["foundation", "--roots", str(portfolio_env)]) == 2
    out = capsys.readouterr().out
    assert "error: no foundational repos" in out
