from datetime import date
from portfolio.add import add_item, infer_repo
from portfolio.manifest import read_manifest

NOW = "2026-06-25T10:00:00.000000"

def test_explicit_repo_clean_tree_writes_through(make_repo, portfolio_env):
    repo = make_repo("contacts", files={"package.json": '{"version":"1.0.0"}'})
    item = add_item("add carddav", repo=repo, cwd=repo, session="s1", today=date(2026,6,25), now_iso=NOW)
    assert item.status == "triaged" and "add carddav" in read_manifest(repo).body

def test_ambiguous_capture_stays_in_inbox(tmp_path, portfolio_env):
    item = add_item("vague idea", cwd=tmp_path, roots=[tmp_path / "nope"], session="s1",
                    today=date(2026,6,25), now_iso=NOW)
    assert item.status == "untriaged" and item.inferred_repo is None

def test_dirty_tree_does_not_write_through(make_repo, portfolio_env):
    repo = make_repo("contacts")
    (repo / "dirty.txt").write_text("x")
    item = add_item("later", repo=repo, cwd=repo, session="s1", today=date(2026,6,25), now_iso=NOW)
    assert item.status == "untriaged" and read_manifest(repo) is None

def test_nonexistent_repo_does_not_crash(tmp_path, portfolio_env):
    item = add_item("x", repo=tmp_path / "missing", cwd=tmp_path, session="s",
                    today=date(2026,6,25), now_iso=NOW)
    assert item.status == "untriaged"   # invalid repo → inbox only, no exception

def test_invalid_explicit_repo_stays_inbox_even_under_root(make_repo, portfolio_env, tmp_path):
    # cwd IS a valid project under a root, but a typo'd explicit --repo must NOT infer/write-through
    real = make_repo("contacts", files={"package.json": '{"version":"1.0.0"}'})
    item = add_item("typoed target", repo=tmp_path / "missing", cwd=real,
                    roots=[tmp_path], session="s", today=date(2026,6,25), now_iso=NOW)
    assert item.status == "untriaged"
    assert item.inferred_repo is None

def test_infer_repo_boundaries(tmp_path):
    (tmp_path / "proj").mkdir()
    got, conf = infer_repo(tmp_path / "proj", [tmp_path])
    assert got is not None and got.name == "proj" and conf == 0.9
    assert infer_repo(tmp_path, [tmp_path]) == (None, 0.0)          # cwd == root → no project
