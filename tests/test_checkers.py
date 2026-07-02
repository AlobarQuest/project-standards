import subprocess

from portfolio.checkers import _run, check_project
from portfolio.matrix import PASS, VIOLATION


def _good_active():
    return ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\n"
            "version_source: package.json\npurpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n")


def _good_parking():
    return "---\nname: x\ntier: parking\nstatus: idea\npurpose: p\n---\n\n## Backlog\n"


def test_run_returns_completed_process_on_nonzero_exit():
    result = _run(["false"])
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 1


def test_run_returns_none_on_missing_command():
    assert _run(["definitely-not-a-command-xyz"]) is None


def test_check_project_missing_manifest_is_violation(make_repo):
    repo = make_repo("x")
    result = check_project(repo)
    assert result.standard == "project"
    assert result.status == VIOLATION
    assert any(d["id"] == "project.missing_manifest" for d in result.details)


def test_check_project_valid_active_repo_is_pass(make_repo):
    repo = make_repo("x", files={"PROJECT.md": _good_active(), "package.json": '{"version":"1.0.0"}'})
    result = check_project(repo)
    assert result.status == PASS
    assert all(not d["id"].endswith("missing_manifest") for d in result.details)


def test_check_project_parking_non_git_is_pass_with_warn_detail(make_repo):
    repo = make_repo("x", git=False, files={"PROJECT.md": _good_parking()})
    result = check_project(repo)
    assert result.status == PASS
    assert any(d["id"] == "project.not_git" for d in result.details)
