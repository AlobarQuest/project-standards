import subprocess

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


def test_origin_advanced_fires_with_fix_commands(tmp_path):
    origin, checkout = _clone_with_origin(tmp_path)
    (origin / "README.md").write_text("advanced\n")
    subprocess.run(["git", "add", "-A"], cwd=origin, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "advance"],
        cwd=origin,
        check=True,
    )
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
