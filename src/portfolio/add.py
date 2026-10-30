import subprocess
from datetime import date
from pathlib import Path

from . import config
from .detect import is_git
from .inbox import InboxItem, append_inbox, new_id
from .init import init_repo
from .manifest import append_backlog_item


def home_repo(path: Path) -> Path:
    """Map a path inside <repo>/.worktrees/<name> to <repo> when <repo> is a git checkout.

    A backlog item belongs in the main checkout's PROJECT.md, not on a feature branch, and the
    worktree is usually deleted long before anyone triages the item.
    """
    path = Path(path).resolve()
    parts = path.parts
    if ".worktrees" in parts[1:]:
        main = Path(*parts[: parts.index(".worktrees")])
        if is_git(main):
            return main
    return path


def infer_repo(cwd: Path, roots: list[Path]) -> tuple[Path | None, float]:
    cwd = Path(cwd).resolve()
    for root in roots:
        root = Path(root).resolve()
        if cwd == root or root in cwd.parents:
            rel = cwd.relative_to(root)
            if rel.parts:
                return root / rel.parts[0], 0.9
    return None, 0.0


CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


def write_block(repo: Path) -> str | None:
    """Why a capture must not write into repo's PROJECT.md now, or None if it may.

    Changes to PROJECT.md itself don't block: every write-through modifies it, so counting it
    would send every capture after the first one in a session to the inbox. A conflicted
    PROJECT.md does block. An untracked .worktrees/ directory is not a change to the repo.
    """
    if not is_git(repo):
        return "not a git repo"
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, timeout=5
        )
    except subprocess.SubprocessError, OSError:
        return "git status failed"
    if out.returncode != 0:
        return "git status failed"
    for line in out.stdout.splitlines():
        code, path = line[:2], line[3:]
        if path == "PROJECT.md":
            if code in CONFLICT_CODES:
                return "PROJECT.md has a merge conflict"
        elif not (code == "??" and path.rstrip("/") == ".worktrees"):
            return "uncommitted changes"
    manifest = repo / "PROJECT.md"
    if manifest.exists() and "\n<<<<<<< " in "\n" + manifest.read_text():
        return "PROJECT.md has a merge conflict"
    return None


def _valid_repo(repo) -> Path | None:
    if repo is None:
        return None
    repo = home_repo(repo)
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

    can_write = repo is not None and write_block(repo) is None
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
