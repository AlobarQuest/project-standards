import json
import subprocess

from portfolio.onboard_checks import check_ci_executed, check_code_onboarded


def _repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/AlobarQuest/repo.git"],
        cwd=repo,
        check=True,
    )
    return repo


ONBOARDED = {
    ".code-standards.toml": "[languages]\n",
    ".github/workflows/quality.yml": "name: Quality\n",
}


def test_code_onboarded_missing_manifest_fires(tmp_path):
    repo = _repo(tmp_path, {".github/workflows/quality.yml": "name: Quality\n"})
    result = check_code_onboarded(repo)
    assert result["status"] == "violation"
    assert "code-standards init" in result["fix"]


def test_code_onboarded_missing_workflow_fires(tmp_path):
    repo = _repo(tmp_path, {".code-standards.toml": "[languages]\n"})
    result = check_code_onboarded(repo)
    assert result["status"] == "violation"
    assert "code-standards sync" in result["fix"]


def test_code_onboarded_passes(tmp_path):
    repo = _repo(tmp_path, ONBOARDED)
    assert check_code_onboarded(repo)["status"] == "pass"


def _fake_gh(run_list=None, log=None):
    calls = []

    def gh(args):
        calls.append(args)
        if args[:2] == ["run", "list"]:
            return run_list
        if args[:2] == ["run", "view"]:
            return log
        raise AssertionError(f"unexpected gh args: {args}")

    gh.calls = calls
    return gh


RUN_OK = json.dumps([{"databaseId": 42, "conclusion": "success"}])


def test_ci_executed_reads_collected_count(tmp_path):
    repo = _repo(tmp_path, ONBOARDED)
    gh = _fake_gh(run_list=RUN_OK, log="...\ncollected 227 items\n...")
    result = check_ci_executed(repo, gh=gh)
    assert result["status"] == "pass"
    assert any("227" in d["message"] for d in result["details"])
    assert ["run", "list", "--repo", "AlobarQuest/repo"] == gh.calls[0][:4]


def test_ci_executed_zero_collected_fires(tmp_path):
    repo = _repo(tmp_path, ONBOARDED)
    gh = _fake_gh(run_list=RUN_OK, log="collected 0 items\n")
    result = check_ci_executed(repo, gh=gh)
    assert result["status"] == "violation"


def test_ci_executed_green_but_ran_nothing_fires(tmp_path):
    """The trap this check exists for: conclusion success, no collected line."""
    repo = _repo(tmp_path, ONBOARDED)
    gh = _fake_gh(run_list=RUN_OK, log="pytest not installed — skipping\n")
    result = check_ci_executed(repo, gh=gh)
    assert result["status"] == "violation"
    assert "collected" in result["fix"]


def test_ci_executed_failed_conclusion_fires(tmp_path):
    repo = _repo(tmp_path, ONBOARDED)
    gh = _fake_gh(run_list=json.dumps([{"databaseId": 42, "conclusion": "failure"}]))
    result = check_ci_executed(repo, gh=gh)
    assert result["status"] == "violation"


def test_ci_executed_gh_unavailable_is_unknown_never_green(tmp_path):
    repo = _repo(tmp_path, ONBOARDED)
    result = check_ci_executed(repo, gh=_fake_gh(run_list=None))
    assert result["status"] == "unknown"


def test_ci_executed_no_runs_is_unknown(tmp_path):
    repo = _repo(tmp_path, ONBOARDED)
    result = check_ci_executed(repo, gh=_fake_gh(run_list="[]"))
    assert result["status"] == "unknown"
