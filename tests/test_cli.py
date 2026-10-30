from portfolio import config
from portfolio.cli import main
from portfolio.matrix import PASS, CheckResult


def test_cli_scan_runs_and_writes(make_repo, portfolio_env, capsys, monkeypatch):
    monkeypatch.setattr("portfolio.member_scope.read_granted", lambda: frozenset({"o/x"}))
    body = (
        "---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: package.json\n"
        "purpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n"
    )
    repo = make_repo("x", files={"PROJECT.md": body})
    assert main(["scan", "--roots", str(repo.parent)]) == 0
    assert config.json_path().exists() and "projects" in capsys.readouterr().out


def test_cli_lint_nonzero_on_fail(make_repo, portfolio_env):
    assert main(["lint", str(make_repo("x"))]) == 1  # no PROJECT.md → FAIL


def test_cli_add_accepts_multiword(make_repo, portfolio_env, monkeypatch):
    repo = make_repo("contacts", files={"package.json": '{"version":"1.0.0"}'})
    monkeypatch.chdir(repo)
    assert main(["add", "fix", "the", "login", "flow", "--repo", str(repo)]) == 0


def test_cli_triage_assign_without_repo_errors(portfolio_env):
    assert main(["triage", "--assign", "abc"]) == 2


def test_cli_foundation_valid_repo_returns_zero(
    make_repo, portfolio_env, capsys, monkeypatch, standards_env
):
    """Valid foundational repo with [project] only → returns 0, capsys contains 'foundation: 1 repos' and 'violations=0'."""
    # Monkeypatch check_governance to return PASS (cheaper than a real run)
    monkeypatch.setattr(
        "portfolio.checkers.check_governance", lambda: CheckResult("governance", PASS)
    )

    body = (
        "---\nname: foundational\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: package.json\n"
        "purpose: core infra\nupdated: 2026-06-25\nfoundation: true\n"
        "applicable_standards:\n  project: '1.0'\n"
        "required_checks:\n- id: quality\n  executor: github-actions:quality.yml\n"
        "---\n\n## Backlog\n"
    )
    repo = make_repo("foundational", files={"PROJECT.md": body})
    wf = repo / ".github" / "workflows" / "quality.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("jobs:\n  quality: {}\n")

    assert main(["foundation", "--roots", str(repo.parent)]) == 0
    out = capsys.readouterr().out
    assert "foundation: 1 repos" in out
    assert "violations=0" in out


def test_cli_foundation_broken_manifest_returns_one(
    make_repo, portfolio_env, capsys, monkeypatch, standards_env
):
    """Broken manifest (missing required fields) → returns 1, output contains 'violations=1'."""
    monkeypatch.setattr(
        "portfolio.checkers.check_governance", lambda: CheckResult("governance", PASS)
    )

    # Missing required fields for active tier (status, version, version_source)
    body = (
        "---\nname: broken\ntier: active\npurpose: broken\nupdated: 2026-06-25\nfoundation: true\n"
        "applicable_standards:\n  project: '1.0'\n"
        "required_checks:\n- id: quality\n  executor: github-actions:quality.yml\n"
        "---\n\n## Backlog\n"
    )
    repo = make_repo("broken", files={"PROJECT.md": body})
    wf = repo / ".github" / "workflows" / "quality.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("jobs:\n  quality: {}\n")

    assert main(["foundation", "--roots", str(repo.parent)]) == 1
    out = capsys.readouterr().out
    assert "violations=1" in out


def test_cli_foundation_malformed_exceptions_toml_returns_two(
    make_repo, portfolio_env, capsys, monkeypatch, tmp_path
):
    """Malformed FOUNDATION_EXCEPTIONS TOML → returns 2, output starts with 'error:'."""
    monkeypatch.setattr(
        "portfolio.checkers.check_governance", lambda: CheckResult("governance", PASS)
    )

    # Create a malformed TOML file and set it as the exceptions path
    exceptions_file = tmp_path / "bad.toml"
    exceptions_file.write_text("this is not [valid toml")
    monkeypatch.setenv("FOUNDATION_EXCEPTIONS", str(exceptions_file))

    body = (
        "---\nname: foundational\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: package.json\n"
        "purpose: core\nupdated: 2026-06-25\nfoundation: true\napplicable_standards: [project]\n---\n\n## Backlog\n"
    )
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


def test_cli_triage_plain_keeps_one_line_per_item(portfolio_env, capsys):
    from portfolio.inbox import InboxItem, append_inbox

    append_inbox(
        InboxItem("abc123", "2026-10-30T09:00:00", "do x", None, 0.0, None, "P2", "untriaged")
    )
    assert main(["triage", "--plain"]) == 0
    assert capsys.readouterr().out == "abc123  conf=0.0  do x\n"


def test_cli_triage_show_prints_full_text(portfolio_env, capsys):
    from portfolio.inbox import InboxItem, append_inbox

    long = "word " * 60
    append_inbox(
        InboxItem("abc123", "2026-10-30T09:00:00", long, None, 0.0, None, None, "untriaged")
    )
    assert main(["triage", "--show", "abc123"]) == 0
    assert long.strip() in capsys.readouterr().out
    assert main(["triage", "--show", "nope"]) == 1


def test_cli_file_inferred_needs_yes_to_write(make_repo, portfolio_env, capsys):
    from portfolio.inbox import InboxItem, append_inbox
    from portfolio.manifest import read_manifest

    repo = make_repo("alpha", files={"package.json": '{"version":"1.0.0"}'})
    append_inbox(
        InboxItem("abc123", "2026-10-30T09:00:00", "do x", str(repo), 0.9, None, None, "untriaged")
    )
    assert main(["triage", "--file-inferred"]) == 0
    assert read_manifest(repo) is None and "--yes" in capsys.readouterr().out
    assert main(["triage", "--file-inferred", "--yes"]) == 0
    assert "do x" in read_manifest(repo).body


def test_cli_triage_rejects_conflicting_flags(portfolio_env):
    assert main(["triage", "--yes"]) == 2
    assert main(["triage", "--file-inferred", "--assign", "abc", "--repo", "/tmp"]) == 2
