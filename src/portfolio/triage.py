from datetime import date
from pathlib import Path

from .inbox import InboxItem, mark_triaged, read_inbox
from .init import init_repo
from .manifest import append_backlog_item


def untriaged() -> list[InboxItem]:
    return [i for i in read_inbox() if i.status == "untriaged"]


def assign(item_id: str, repo: Path, today: date | None = None) -> None:
    today = today or date.today()
    item = next((i for i in read_inbox() if i.id == item_id), None)
    if item is None:
        raise KeyError(item_id)
    init_repo(repo, today=today)
    append_backlog_item(repo, item.text, item.priority, today.isoformat())
    mark_triaged(item_id)
