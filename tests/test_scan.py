from datetime import date
from portfolio.scan import scan
from portfolio import config
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
