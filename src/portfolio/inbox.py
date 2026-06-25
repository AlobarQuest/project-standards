import hashlib
import json
from dataclasses import dataclass, asdict

from . import config

@dataclass
class InboxItem:
    id: str
    ts: str
    text: str
    inferred_repo: str | None
    confidence: float
    source_session: str | None
    priority: str | None
    status: str  # "untriaged" | "triaged"

def new_id(text: str, ts: str) -> str:
    return hashlib.sha256(f"{text}|{ts}".encode()).hexdigest()[:12]

def append_inbox(item: InboxItem) -> None:
    path = config.inbox_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(item)) + "\n")

def read_inbox() -> list[InboxItem]:
    path = config.inbox_path()
    if not path.exists():
        return []
    items: dict[str, InboxItem] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:                                       # [debate-fix] isolate bad lines
            d = json.loads(line)
            items[d["id"]] = InboxItem(**d)        # later status updates win
        except (json.JSONDecodeError, TypeError, KeyError):
            continue
    return list(items.values())

def mark_triaged(item_id: str) -> None:
    for item in read_inbox():
        if item.id == item_id:
            item.status = "triaged"
            append_inbox(item)
            return

def find_duplicate(text: str) -> InboxItem | None:
    norm = text.strip().lower()
    for item in read_inbox():
        if item.text.strip().lower() == norm and item.status == "untriaged":
            return item
    return None
