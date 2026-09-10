import hashlib
import os
import subprocess
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("origin_moved", [True, False])
def test_the_check_leaves_the_working_tree_byte_identical(tmp_path, origin_moved):
    """The module docstring's read-only claim, split the way it is actually true.

    The kit is read-only against the target's WORKING TREE and is not read-only
    against its `.git/`. Both halves are asserted here.

    BOTH PATHS ARE EXERCISED, and that is not thoroughness for its own sake: an
    advanced origin makes `HEAD != origin/main`, so the check returns at the ref
    comparison and never reaches `git status --porcelain`. A test written on
    that path alone would pin the working-tree claim for two of the four git
    subcommands. The advanced case is still needed — against an already-current
    origin, a fetch that had silently stopped fetching would pass unnoticed.

    `.git` is deliberately not fingerprinted: the fetch's own writes are the
    point, and on the advanced path they include objects.
    """
    origin, checkout = _clone_with_origin(tmp_path)
    if origin_moved:
        _advance_origin(origin)
    stale = _rev(checkout, "origin/main")
    before = _tree_fingerprint(checkout)
    assert not (checkout / ".git" / "FETCH_HEAD").exists()

    result = check_git_current(checkout)

    assert _tree_fingerprint(checkout) == before
    assert (checkout / ".git" / "FETCH_HEAD").exists()
    if origin_moved:
        # The fetch moved the remote-tracking ref, so the untouched tree is a
        # measurement rather than an artefact of nothing having run.
        assert result["status"] == "violation"
        assert _rev(checkout, "origin/main") != stale
    else:
        # Runs past the ref comparison to `git status --porcelain`.
        assert result["status"] == "pass"
        assert _rev(checkout, "origin/main") == stale


def test_the_working_tree_fingerprint_would_notice_a_write(tmp_path):
    """Positive control for the test above: a fingerprint that discriminates.

    Without this, a `_tree_fingerprint` that returned `{}` — or that walked the
    wrong directory — would satisfy the byte-identical assertion vacuously.
    """
    _, checkout = _clone_with_origin(tmp_path)
    before = _tree_fingerprint(checkout)
    (checkout / "README.md").write_text("written by something\n")
    assert _tree_fingerprint(checkout) != before


def test_the_working_tree_fingerprint_would_notice_a_same_content_rewrite(tmp_path):
    """Second control, because `st_mtime_ns` is the component nothing else pins.

    The control above changes content, size and mtime together, so it passes
    against a fingerprint that had dropped mtime. Mtime is the only component
    that catches a rewrite of a file with its own bytes — the shape a
    working-tree write would most plausibly take here, since `git checkout -- .`
    over a clean tree touches every file and changes none of them.
    """
    _, checkout = _clone_with_origin(tmp_path)
    before = _tree_fingerprint(checkout)
    readme = checkout / "README.md"
    readme.write_bytes(readme.read_bytes())
    os.utime(readme, (0, 0))
    assert _tree_fingerprint(checkout) != before
