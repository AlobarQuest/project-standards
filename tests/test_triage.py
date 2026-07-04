from datetime import date

import pytest

from portfolio.inbox import InboxItem, append_inbox, new_id, read_inbox
from portfolio.manifest import read_manifest
from portfolio.triage import assign, untriaged


def _untriaged(text="do x"):
    return InboxItem(
        id=new_id(text, "t"),
        ts="t",
        text=text,
        inferred_repo=None,
        confidence=0.0,
        source_session=None,
        priority="P2",
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
