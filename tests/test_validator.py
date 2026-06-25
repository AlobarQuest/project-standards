from datetime import date
from portfolio.validator import lint

def _good_active():
    return ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\n"
            "version_source: package.json\npurpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n")

def test_missing_manifest_is_fail(make_repo):
    assert any(f.code == "missing_manifest" and f.severity == "FAIL" for f in lint(make_repo("x")))

def test_conforming_active_repo_is_clean(make_repo):
    repo = make_repo("x", files={"PROJECT.md": _good_active(), "package.json": '{"version":"1.0.0"}'})
    assert lint(repo, today=date(2026, 6, 26)) == []

def test_bad_yaml_is_fail(make_repo):
    repo = make_repo("x", files={"PROJECT.md": "---\nname: x\n bad: : :\n---\n"})
    assert any(f.code == "bad_yaml" and f.severity == "FAIL" for f in lint(repo, today=date(2026,6,26)))

def test_non_git_active_is_fail(make_repo):
    repo = make_repo("x", git=False, files={"PROJECT.md": _good_active().replace("1.0.0","n/a").replace("package.json","none")})
    assert any(f.code == "not_git" and f.severity == "FAIL" for f in lint(repo, today=date(2026,6,26)))

def test_aged_backlog_item_is_warn(make_repo):
    body = _good_active().replace("## Backlog\n", "## Backlog\n- [ ] (P3) old — added 2025-01-01\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    assert any(f.code == "aged_item" and f.severity == "WARN" for f in lint(repo, today=date(2026,6,26)))
