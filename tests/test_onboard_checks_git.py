import hashlib
import os
import subprocess
from pathlib import Path

from portfolio.onboard_checks import check_git_current


def _clone_with_origin(tmp_path, name="checkout"):
    origin = tmp_path / f"{name}-origin"
    origin.mkdir()
    (origin / "README.md").write_text("hello\n")
    for argv in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
    ):
        subprocess.run(["git", *argv], cwd=origin, check=True)
    checkout = tmp_path / name
    subprocess.run(
        ["git", "clone", "--quiet", str(origin), str(checkout)], check=True, capture_output=True
    )
    return origin, checkout


def test_current_clean_checkout_passes(tmp_path):
    _, checkout = _clone_with_origin(tmp_path)
    result = check_git_current(checkout)
    assert result["id"] == "git.current"
    assert result["status"] == "pass"


def _advance_origin(origin):
    (origin / "README.md").write_text("advanced\n")
    subprocess.run(["git", "add", "-A"], cwd=origin, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "advance"],
        cwd=origin,
        check=True,
    )


def _tree_fingerprint(root: Path) -> dict:
    """Every file OUTSIDE `.git`, by content, size and mtime."""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        if ".git" in dirnames:
            dirnames.remove(".git")
        for name in filenames:
            path = Path(dirpath) / name
            stat = path.lstat()
            out[str(path.relative_to(root))] = (
                hashlib.sha256(path.read_bytes()).hexdigest(),
                stat.st_size,
                stat.st_mtime_ns,
            )
    return out


def _rev(repo: Path, ref: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_origin_advanced_fires_with_fix_commands(tmp_path):
    origin, checkout = _clone_with_origin(tmp_path)
    _advance_origin(origin)
    result = check_git_current(checkout)
    assert result["status"] == "violation"
    assert "pull --ff-only origin main" in result["fix"]


def test_dirty_worktree_fires(tmp_path):
    _, checkout = _clone_with_origin(tmp_path)
    (checkout / "README.md").write_text("dirty\n")
    result = check_git_current(checkout)
    assert result["status"] == "violation"
    assert "uncommitted" in result["details"][0]["message"]


def test_missing_origin_fires_never_green(tmp_path):
    repo = tmp_path / "loner"
    repo.mkdir()
    (repo / "README.md").write_text("x\n")
    for argv in (
        ["init", "-q", "-b", "main"],
        ["add", "-A"],
        ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
    ):
        subprocess.run(["git", *argv], cwd=repo, check=True)
    result = check_git_current(repo)
    assert result["status"] == "violation"
    assert "fetch" in result["details"][0]["message"]


def test_the_check_leaves_the_working_tree_byte_identical(tmp_path):
    """The module docstring's read-only claim, split the way it is actually true.

    The kit is read-only against the target's WORKING TREE and is not read-only
    against its `.git/`. Both halves are asserted here, and the origin is
    advanced first so the fetch has real work to do — against an already-current
    origin a fetch that had silently stopped fetching would pass this test.

    `.git` mtimes are deliberately NOT asserted wholesale: the check's own
    `git status --porcelain` refreshes `.git/index`'s stat cache, which is a
    write to `.git/` and not a write to the tree.
    """
    origin, checkout = _clone_with_origin(tmp_path)
    _advance_origin(origin)
    stale = _rev(checkout, "origin/main")
    before = _tree_fingerprint(checkout)
    assert not (checkout / ".git" / "FETCH_HEAD").exists()

    result = check_git_current(checkout)

    assert _tree_fingerprint(checkout) == before
    # The fetch happened and moved the remote-tracking ref, so the tree being
    # untouched is a measurement rather than an artefact of nothing running.
    assert result["status"] == "violation"
    assert _rev(checkout, "origin/main") != stale
    assert (checkout / ".git" / "FETCH_HEAD").exists()


def test_the_working_tree_fingerprint_would_notice_a_write(tmp_path):
    """Positive control for the test above: a fingerprint that discriminates.

    Without this, a `_tree_fingerprint` that returned `{}` — or that walked the
    wrong directory — would satisfy the byte-identical assertion vacuously.
    """
    _, checkout = _clone_with_origin(tmp_path)
    before = _tree_fingerprint(checkout)
    (checkout / "README.md").write_text("written by something\n")
    assert _tree_fingerprint(checkout) != before
