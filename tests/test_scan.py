from datetime import date
from portfolio.scan import scan
from portfolio import config
import json

def test_scan_writes_artifacts(make_repo, portfolio_env):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: package.json\n"
            "purpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    summary = scan(roots=[repo.parent], today=date(2026,6,26))
    assert summary["projects"] == 1
    assert config.json_path().exists() and config.digest_path().exists()
    assert json.loads(config.json_path().read_text())["projects"][0]["name"] == "x"
