from datetime import date

import pytest

from portfolio.inbox import InboxItem, append_inbox, new_id, read_inbox
from portfolio.manifest import read_manifest
from portfolio.triage import assign, file_inferred, render_inbox, untriaged


def _untriaged(text="do x", repo=None, ts="2026-10-30T09:00:00", priority="P2"):
    return InboxItem(
        id=new_id(text, ts),
        ts=ts,
        text=text,
        inferred_repo=str(repo) if repo else None,
        confidence=0.9 if repo else 0.0,
        source_session=None,
        priority=priority,
        status="untriaged",
    )


def test_assign_writes_into_repo_and_marks_triaged(make_repo, portfolio_env):
    it = _untriaged()
    append_inbox(it)
    repo = make_repo("target")
    assign(it.id, repo, today=date(2026, 6, 25))
    assert "do x" in read_manifest(repo).body
    assert all(i.status == "triaged" for i in read_inbox() if i.id == it.id)
    assert untriaged() == []


def test_assign_unknown_id_raises(portfolio_env, make_repo):
    with pytest.raises(KeyError):
        assign("nope", make_repo("r"))


def test_render_groups_by_repo_with_unplaced_last(tmp_path):
    items = [
        _untriaged("no home"),
        _untriaged("zeta item", repo=tmp_path / "zeta"),
        _untriaged("alpha one", repo=tmp_path / "alpha"),
        _untriaged("alpha two", repo=tmp_path / "alpha", ts="2026-10-31T09:00:00"),
    ]
    lines = render_inbox(items).splitlines()
    headers = [ln for ln in lines if ln and not ln.startswith(" ")]
    assert headers[:4] == ["4 untriaged items", "alpha (2)", "zeta (1)", "no repo inferred (1)"]


def test_render_line_shows_id_priority_date_and_shortened_text(tmp_path):
    it = _untriaged("word " * 100, repo=tmp_path / "alpha", priority="P1")
    line = next(ln for ln in render_inbox([it]).splitlines() if it.id in ln)
    assert "P1" in line and "2026-10-30" in line
    assert line.rstrip().endswith("…") and len(line) <= 140


def test_render_empty_inbox():
    assert render_inbox([]) == "Inbox is empty."


def test_file_inferred_dry_run_writes_nothing(make_repo, portfolio_env):
    repo = make_repo("alpha", files={"package.json": '{"version":"1.0.0"}'})
    append_inbox(_untriaged("filed later", repo=repo))
    result = file_inferred(apply=False, today=date(2026, 10, 30))
    assert [i.text for i in result.filed] == ["filed later"]
    assert read_manifest(repo) is None and len(untriaged()) == 1


def test_file_inferred_apply_files_and_skips_with_reasons(make_repo, portfolio_env, tmp_path):
    clean = make_repo("alpha", files={"package.json": '{"version":"1.0.0"}'})
    dirty = make_repo("beta")
    (dirty / "wip.txt").write_text("x")
    for it in (
        _untriaged("goes in", repo=clean),
        _untriaged("also goes in", repo=clean, ts="2026-10-30T10:00:00"),
        _untriaged("repo dirty", repo=dirty),
        _untriaged("repo gone", repo=tmp_path / "retired"),
        _untriaged("no home"),
    ):
        append_inbox(it)
    result = file_inferred(apply=True, today=date(2026, 10, 30))
    assert sorted(i.text for i in result.filed) == ["also goes in", "goes in"]
    reasons = {i.text: why for i, why in result.skipped}
    assert reasons == {"repo dirty": "uncommitted changes", "repo gone": "repo not found"}
    body = read_manifest(clean).body
    assert "goes in" in body and "also goes in" in body
    assert sorted(i.text for i in untriaged()) == ["no home", "repo dirty", "repo gone"]


def test_worktree_items_group_and_file_under_the_main_checkout(make_repo, portfolio_env):
    repo = make_repo("orch", files={"package.json": '{"version":"1.0.0"}'})
    it = _untriaged("from a deleted worktree", repo=repo / ".worktrees" / "gone")
    append_inbox(it)
    assert "orch (1)" in render_inbox([it])
    result = file_inferred(apply=True, today=date(2026, 10, 30))
    assert [i.text for i in result.filed] == ["from a deleted worktree"]
    assert "from a deleted worktree" in read_manifest(repo).body
