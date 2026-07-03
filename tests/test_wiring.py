import json

import pytest

from portfolio.wiring import check_required_checks


@pytest.fixture
def machine(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"Stop": [{"matcher": ".*", "hooks": [
        {"type": "command", "command": "/Users/devon/.claude/hooks/bws-scan-gate.sh"}
    ]}]}}))
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    (agents / "com.devon.security-scan.plist").write_text("<plist/>")
    monkeypatch.setenv("CLAUDE_SETTINGS_JSON", str(settings))
    monkeypatch.setenv("LAUNCHAGENTS_DIR", str(agents))


def _repo(tmp_path, workflow="quality.yml", body="jobs:\n  quality:\n    steps: []\n"):
    repo = tmp_path / "r"
    wf = repo / ".github" / "workflows" / workflow
    wf.parent.mkdir(parents=True)
    wf.write_text(body)
    return repo


def _ids(result):
    return [d["id"] for d in result.details]


def test_none_declared_foundation_vs_not(tmp_path, machine):
    repo = tmp_path / "empty"
    repo.mkdir()
    assert _ids(check_required_checks(repo, [], foundation=True)) == ["checks.none-declared"]
    assert check_required_checks(repo, [], foundation=False).status == "not-applicable"


def test_workflow_wired_and_missing(tmp_path, machine):
    repo = _repo(tmp_path)
    ok = check_required_checks(
        repo, [{"id": "quality", "executor": "github-actions:quality.yml"}], True)
    assert ok.status == "pass"
    missing = check_required_checks(
        repo, [{"id": "x", "executor": "github-actions:nope.yml"}], True)
    assert _ids(missing) == ["checks.not-wired"]


def test_workflow_job_key_checked(tmp_path, machine):
    repo = _repo(tmp_path)
    ok = check_required_checks(
        repo, [{"id": "q", "executor": "github-actions:quality.yml:quality"}], True)
    assert ok.status == "pass"
    bad = check_required_checks(
        repo, [{"id": "q", "executor": "github-actions:quality.yml:missing"}], True)
    assert _ids(bad) == ["checks.not-wired"]


def test_hook_checks_settings_registration(tmp_path, machine):
    repo = tmp_path / "r2"
    repo.mkdir()
    ok = check_required_checks(repo, [{"id": "gate", "executor": "hook:bws-scan-gate.sh"}], True)
    assert ok.status == "pass"
    bad = check_required_checks(repo, [{"id": "g", "executor": "hook:unregistered.sh"}], True)
    assert _ids(bad) == ["checks.not-wired"]


def test_hook_path_fragment_not_wired(tmp_path, machine):
    repo = tmp_path / "r2b"
    repo.mkdir()
    bad = check_required_checks(repo, [{"id": "g", "executor": "hook:gate.sh"}], True)
    assert _ids(bad) == ["checks.not-wired"]


def test_hook_json_key_command_not_wired(tmp_path, machine):
    repo = tmp_path / "r2c"
    repo.mkdir()
    bad = check_required_checks(repo, [{"id": "g", "executor": "hook:command"}], True)
    assert _ids(bad) == ["checks.not-wired"]


def test_hook_json_key_event_not_wired(tmp_path, machine):
    repo = tmp_path / "r2d"
    repo.mkdir()
    bad = check_required_checks(repo, [{"id": "g", "executor": "hook:Stop"}], True)
    assert _ids(bad) == ["checks.not-wired"]


def test_launchagent_plist_existence(tmp_path, machine):
    repo = tmp_path / "r3"
    repo.mkdir()
    ok = check_required_checks(
        repo, [{"id": "scan", "executor": "launchagent:com.devon.security-scan"}], True)
    assert ok.status == "pass"
    bad = check_required_checks(
        repo, [{"id": "s", "executor": "launchagent:com.devon.nope"}], True)
    assert _ids(bad) == ["checks.not-wired"]


def test_bad_executor_and_malformed_entry(tmp_path, machine):
    repo = tmp_path / "r4"
    repo.mkdir()
    result = check_required_checks(repo, [
        {"id": "a", "executor": "carrier-pigeon:coop"},
        {"executor": "github-actions:quality.yml"},        # missing id
        "quality",                                          # not a mapping
    ], True)
    assert _ids(result) == ["checks.bad-executor"] * 3
    assert result.status == "violation"
