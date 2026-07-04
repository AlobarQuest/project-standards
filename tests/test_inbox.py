from portfolio import config
from portfolio.inbox import InboxItem, append_inbox, mark_triaged, new_id, read_inbox


def _item(text="do x"):
    return InboxItem(
        id=new_id(text, "2026-06-25T10:00:00.000000"),
        ts="2026-06-25T10:00:00.000000",
        text=text,
        inferred_repo=None,
        confidence=0.0,
        source_session="s1",
        priority=None,
        status="untriaged",
    )


def test_append_and_read_roundtrip(portfolio_env):
    append_inbox(_item("alpha"))
    append_inbox(_item("beta"))
    assert [i.text for i in read_inbox()] == ["alpha", "beta"]


def test_mark_triaged_updates_status(portfolio_env):
    it = _item("gamma")
    append_inbox(it)
    mark_triaged(it.id)
    assert read_inbox()[0].status == "triaged"


def test_malformed_line_is_skipped(portfolio_env):
    append_inbox(_item("good"))
    with config.inbox_path().open("a") as f:
        f.write("{ this is not valid json\n")
    assert [i.text for i in read_inbox()] == ["good"]  # bad line ignored, no crash
