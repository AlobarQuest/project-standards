import subprocess
from datetime import date
from pathlib import Path

from . import config
from .detect import is_git
from .inbox import InboxItem, append_inbox, new_id
from .init import init_repo
from .manifest import append_backlog_item


def infer_repo(cwd: Path, roots: list[Path]) -> tuple[Path | None, float]:
    cwd = Path(cwd).resolve()
    for root in roots:
        root = Path(root).resolve()
        if cwd == root or root in cwd.parents:
            rel = cwd.relative_to(root)
            if rel.parts:
                return root / rel.parts[0], 0.9
    return None, 0.0


def tree_clean(repo: Path) -> bool:
    if not is_git(repo):
        return False
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, timeout=5
        )
        return out.returncode == 0 and out.stdout.strip() == ""
    except (subprocess.SubprocessError, OSError):
        return False


def _valid_repo(repo) -> Path | None:
    if repo is None:
        return None
    repo = Path(repo)
    return repo if repo.exists() and repo.is_dir() else None


def add_item(
    text, *, repo=None, priority=None, cwd, session=None, roots=None, today=None, now_iso
) -> InboxItem:
    today = today or date.today()
    roots = roots or config.DEFAULT_ROOTS
    explicit = repo is not None
    repo = _valid_repo(repo)
    confidence = 1.0 if repo else 0.0
    if repo is None and not explicit:
        repo, confidence = infer_repo(cwd, roots)

    can_write = repo is not None and tree_clean(repo)
    item = InboxItem(
        id=new_id(text, now_iso),
        ts=now_iso,
        text=text,
        inferred_repo=str(repo) if repo else None,
        confidence=confidence,
        source_session=session,
        priority=priority,
        status="untriaged",
    )
    append_inbox(item)  # [debate-fix] untriaged first
    if can_write and repo is not None:
        try:
            init_repo(repo, today=today)
            append_backlog_item(repo, text, priority, today.isoformat())
        except Exception:
            return item  # leave untriaged on failure
        item.status = "triaged"
        append_inbox(item)  # status update only after success
    return item
