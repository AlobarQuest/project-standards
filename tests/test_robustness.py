from datetime import date
from portfolio.scan import scan
from portfolio.aggregate import build_records

def test_scan_survives_malformed_yaml(make_repo, portfolio_env):
    make_repo("bad", files={"PROJECT.md": "---\nname: x\n bad: : :\n---\n"})
    summary = scan(roots=[(make_repo("bad2").parent)], today=date(2026,6,26))  # same tmp parent
    assert summary["projects"] >= 1   # did not raise

def test_no_commit_repo_does_not_crash(make_repo):
    repo = make_repo("fresh", git=True, commit=False)   # git init, zero commits
    recs = build_records([repo.parent], today=date(2026,6,26))
    rec = next(r for r in recs if r.name == "fresh")
    assert rec.head_date is None and rec.stale is False   # no HEAD → not stale, no crash

def test_manifest_without_backlog_section(make_repo, portfolio_env):
    body = "---\nname: x\ntier: parking\nstatus: idea\npurpose: p\n---\n\njust prose\n"
    repo = make_repo("x", files={"PROJECT.md": body})
    rec = next(r for r in build_records([repo.parent], today=date(2026,6,26)) if r.name == "x")
    assert rec.open_backlog == 0   # no section → zero, not error

def test_completed_items_counted(make_repo):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: n/a\nversion_source: none\n"
            "purpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n- [x] done — added 2026-06-01\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    rec = next(r for r in build_records([repo.parent], today=date(2026,6,26)) if r.name == "x")
    assert rec.open_backlog == 1   # parsed, not malformed
