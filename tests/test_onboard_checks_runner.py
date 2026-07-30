import base64
import json
from pathlib import Path

from portfolio.onboard_checks import check_runner_caller, declared_pin, required_secrets

FIXTURE_WORKFLOW = (Path(__file__).parent / "fixtures" / "factory-runner-workflow.yml").read_text()
PIN = "f1cf3c57c74920c0adb4d03c9828d876198d619e"
SECRETS = [
    "FACTORY_RUNNER_TOKEN",
    "FACTORY_RUNNER_CREDENTIAL_KEY_ID",
    "ANTHROPIC_API_KEY",
    "FACTORY_PR_TOKEN",
]


def _caller(pin):
    return (
        "name: Factory Runner Pilot\n"
        "jobs:\n"
        "  factory-runner:\n"
        f"    uses: AlobarQuest/factory-runner/.github/workflows/factory-runner.yml@{pin}\n"
    )


def _repo(tmp_path, caller=None):
    repo = tmp_path / "repo"
    (repo / ".github" / "workflows").mkdir(parents=True)
    if caller is not None:
        (repo / ".github" / "workflows" / "factory-runner-pilot.yml").write_text(caller)
    (repo / ".git").mkdir()  # slug comes from gh in this check, not git
    return repo


def _fake_gh(pin=PIN, workflow=FIXTURE_WORKFLOW, secret_names=SECRETS, fail_on=()):
    def gh(args):
        joined = " ".join(args)
        for needle in fail_on:
            if needle in joined:
                return None
        if "RECOMMENDED_CALLER_PIN" in joined:
            return json.dumps({"content": base64.b64encode(f"{pin}\n".encode()).decode()})
        if "factory-runner.yml" in joined:
            return json.dumps({"content": base64.b64encode(workflow.encode()).decode()})
        if args[:2] == ["secret", "list"]:
            return json.dumps([{"name": n} for n in secret_names])
        raise AssertionError(f"unexpected gh args: {args}")

    return gh


def test_declared_pin_reads_marker():
    assert declared_pin(gh=_fake_gh()) == PIN


def test_required_secrets_from_workflow_at_sha():
    assert required_secrets(PIN, gh=_fake_gh()) == set(SECRETS)


def test_missing_caller_fires_pointing_at_template(tmp_path):
    repo = _repo(tmp_path, caller=None)
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())
    assert result["status"] == "violation"
    assert "factory-runner-caller.yml" in result["fix"]


def test_main_ref_fires_naming_gap4_class(tmp_path):
    repo = _repo(tmp_path, caller=_caller("main"))
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())
    assert result["status"] == "violation"
    assert "@main" in result["details"][0]["message"]


def test_behind_declared_pin_fires(tmp_path):
    repo = _repo(tmp_path, caller=_caller("a" * 40))
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())
    assert result["status"] == "violation"
    assert "declared pin" in result["details"][0]["message"]


def test_missing_secret_fires_naming_it(tmp_path):
    repo = _repo(tmp_path, caller=_caller(PIN))
    gh = _fake_gh(secret_names=SECRETS[:-1])
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=gh)
    assert result["status"] == "violation"
    assert "FACTORY_PR_TOKEN" in result["details"][0]["message"]


def test_conformant_caller_passes(tmp_path):
    repo = _repo(tmp_path, caller=_caller(PIN))
    assert check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())["status"] == "pass"


def test_declared_pin_unreachable_is_unknown_never_green(tmp_path):
    repo = _repo(tmp_path, caller=_caller(PIN))
    gh = _fake_gh(fail_on=("RECOMMENDED_CALLER_PIN",))
    assert check_runner_caller(repo, "AlobarQuest/repo", gh=gh)["status"] == "unknown"
