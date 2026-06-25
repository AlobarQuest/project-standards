from datetime import date
from portfolio.aggregate import build_records, to_json, render_digest
import json

def _manifest(updated="2026-06-25"):
    return (f"---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: package.json\n"
            f"purpose: does x\nupdated: {updated}\n---\n\n## Backlog\n- [ ] (P1) a — added 2026-06-01\n- [ ] (P2) b — added 2026-06-02\n")

def test_build_records_counts_open_backlog(make_repo):
    repo = make_repo("x", files={"PROJECT.md": _manifest()})
    rec = next(r for r in build_records([repo.parent], today=date(2026,6,26)) if r.name == "x")
    assert rec.open_backlog == 2 and rec.tier == "active"

def test_to_json_and_digest(make_repo):
    repo = make_repo("x", files={"PROJECT.md": _manifest()})
    records = build_records([repo.parent], today=date(2026,6,26))
    data = json.loads(to_json(records, untriaged_count=3))
    assert data["untriaged_count"] == 3 and data["projects"][0]["name"] == "x"
    digest = render_digest(records, untriaged_count=3)
    assert "| x " in digest and "Untriaged inbox items: 3" in digest

def test_stale_manifest_becomes_finding(make_repo):
    # manifest updated long before HEAD commit (make_repo commits at "now") → stale
    repo = make_repo("x", files={"PROJECT.md": _manifest(updated="2025-01-01")})
    rec = next(r for r in build_records([repo.parent], today=date(2026,6,26)) if r.name == "x")
    assert rec.stale is True
    assert any(f["code"] == "stale_manifest" and f["severity"] == "WARN" for f in rec.findings)
