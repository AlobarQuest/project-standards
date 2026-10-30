import textwrap
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .add import home_repo, tree_clean
from .inbox import InboxItem, mark_triaged, read_inbox
from .init import init_repo
from .manifest import append_backlog_item

TEXT_WIDTH = 100
UNPLACED = "no repo inferred"
FOOTER = [
    "Full text:          portfolio triage --show <id>",
    "Place one item:     portfolio triage --assign <id> --repo <path>",
    "File all inferred:  portfolio triage --file-inferred   (preview; add --yes to write)",
]


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


def item_repo(item: InboxItem) -> Path | None:
    return home_repo(Path(item.inferred_repo)) if item.inferred_repo else None


def render_inbox(items: list[InboxItem]) -> str:
    """Group items by inferred repo (unplaced last), one shortened line per item."""
    if not items:
        return "Inbox is empty."
    groups: dict[str, list[InboxItem]] = defaultdict(list)
    for item in items:
        repo = item_repo(item)
        groups[repo.name if repo else UNPLACED].append(item)
    order = sorted((g for g in groups if g != UNPLACED), key=str.lower)
    if UNPLACED in groups:
        order.append(UNPLACED)
    out = [f"{len(items)} untriaged items"]
    for name in order:
        out += ["", f"{name} ({len(groups[name])})"]
        for item in sorted(groups[name], key=lambda i: i.ts):
            text = textwrap.shorten(item.text, TEXT_WIDTH, placeholder=" …")
            out.append(f"  {item.id}  {item.priority or '--'}  {item.ts[:10]}  {text}")
    out += ["", *FOOTER]
    return "\n".join(out)


@dataclass
class FileResult:
    filed: list[InboxItem] = field(default_factory=list)
    skipped: list[tuple[InboxItem, str]] = field(default_factory=list)


def file_inferred(apply: bool, today: date | None = None) -> FileResult:
    """File every untriaged item whose inferred repo exists and is clean.

    With apply=False nothing is written; the result says what would be filed. Items with no
    inferred repo are left for a person and are not reported as skipped.
    """
    result = FileResult()
    clean: dict[Path, bool] = {}
    for item in untriaged():
        repo = item_repo(item)
        if repo is None:
            continue
        if not repo.is_dir():
            result.skipped.append((item, "repo not found"))
            continue
        if repo not in clean:
            clean[repo] = tree_clean(repo)
        if not clean[repo]:
            result.skipped.append((item, "uncommitted changes"))
            continue
        if apply:
            assign(item.id, repo, today=today)
        result.filed.append(item)
    return result
