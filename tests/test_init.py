from datetime import date
from portfolio.init import init_repo
from portfolio.manifest import read_manifest

def test_init_creates_conforming_manifest(make_repo):
    repo = make_repo("contacts", files={"package.json": '{"version":"0.4.2"}', "README.md": "# Contacts\n\nContact hub.\n"})
    init_repo(repo, today=date(2026, 6, 25))
    fm = read_manifest(repo).frontmatter
    assert fm["name"] == "contacts" and fm["version"] == "0.4.2" and fm["version_source"] == "package.json"
    assert fm["purpose"] == "Contact hub." and fm["updated"] == "2026-06-25" and fm["tier"] == "active"

def test_init_does_not_clobber_human_fields(make_repo):
    body = ("---\nname: contacts\ntier: active\nstatus: active\nversion: 9.9.9\nversion_source: package.json\n"
            "purpose: HAND WRITTEN\nupdated: 2026-01-01\n---\n\n## Backlog\n- [ ] (P1) keep me — added 2026-01-01\n")
    repo = make_repo("contacts", files={"PROJECT.md": body, "package.json": '{"version":"0.4.2"}'})
    init_repo(repo, today=date(2026, 6, 25))
    m = read_manifest(repo)
    assert m.frontmatter["purpose"] == "HAND WRITTEN" and m.frontmatter["version"] == "9.9.9" and "keep me" in m.body

def test_init_never_creates_git(make_repo):
    repo = make_repo("scratch", git=False)
    init_repo(repo, tier="parking", today=date(2026, 6, 25))
    assert not (repo / ".git").exists()
