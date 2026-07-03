from datetime import date
from portfolio.scan import scan
from portfolio import config
from portfolio.matrix import CheckResult, PASS
import json

def test_scan_counts_fails(make_repo, portfolio_env):
    from datetime import date
    # active-tier manifest but NOT a git repo -> not_git FAIL
    body = ("---\nname: y\ntier: active\nstatus: active\nversion: n/a\nversion_source: none\n"
            "purpose: p\nupdated: 2026-06-25\n---\n")
    repo = make_repo("y", git=False, files={"PROJECT.md": body})
    summary = scan(roots=[repo.parent], today=date(2026, 6, 26))
    assert summary["projects"] == 1 and summary["fails"] >= 1

def test_scan_writes_artifacts(make_repo, portfolio_env):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: package.json\n"
            "purpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    summary = scan(roots=[repo.parent], today=date(2026,6,26))
    assert summary["projects"] == 1
    assert config.json_path().exists() and config.digest_path().exists()
    assert json.loads(config.json_path().read_text())["projects"][0]["name"] == "x"

def test_scan_attaches_compliance(monkeypatch, make_repo, portfolio_env, standards_env):
    monkeypatch.setattr("portfolio.compliance.checkers.check_project",
                        lambda r: CheckResult("project", PASS))
    declared = make_repo("declared", files={"PROJECT.md": (
        "---\nname: declared\ntier: active\nstatus: active\nversion: 1.0\n"
        "version_source: none\npurpose: p\nupdated: '2026-07-03'\n"
        "applicable_standards:\n  project: '1.0'\n---\n\n## Backlog\n")})
    make_repo("plain", files={"PROJECT.md": (
        "---\nname: plain\ntier: parking\nstatus: idea\npurpose: p\n---\n\n## Backlog\n")})
    make_repo("bare")            # no PROJECT.md

    result = scan(roots=[declared.parent])
    data = json.loads((portfolio_env / "portfolio.json").read_text())
    by_name = {p["name"]: p for p in data["projects"]}
    assert by_name["declared"]["compliance"]["project"]["status"] == "pass"
    assert by_name["plain"]["compliance"]["project"]["status"] == "unknown"
    assert by_name["bare"]["compliance"]["project"]["note"] == "no manifest"
    assert "compliance_violations" in result
    digest = (portfolio_env / "PORTFOLIO.md").read_text()
    assert "## Compliance" in digest
