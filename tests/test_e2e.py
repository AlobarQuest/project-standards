from datetime import date
from portfolio.add import add_item
from portfolio.triage import untriaged, assign
from portfolio.scan import scan
from portfolio.query import query
from portfolio import config
import json

def test_capture_triage_scan_query_loop(make_repo, portfolio_env, tmp_path):
    repo = make_repo("contacts", files={"package.json": '{"version":"1.0.0"}'})
    item = add_item("cross-project idea", cwd=tmp_path, roots=[tmp_path / "none"],
                    session="s", today=date(2026,6,25), now_iso="2026-06-25T10:00:00.000000")
    assert item.status == "untriaged" and len(untriaged()) == 1
    assign(item.id, repo, today=date(2026,6,25))
    assert untriaged() == []
    scan(roots=[repo.parent], today=date(2026,6,26))
    assert json.loads(config.json_path().read_text())["untriaged_count"] == 0
    assert any(p["name"] == "contacts" for p in query({"tier": "active"}))
