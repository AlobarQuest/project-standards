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


# --------------------------------------------------------------------------
# ADR-0015: Q2's one read of Q1
# --------------------------------------------------------------------------

MANIFEST = (
    "---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: pyproject\n"
    "purpose: p\nupdated: 2026-08-17\n{extra}---\n\n## Backlog\n"
)


def _declaring(tmp_path, extra, caller=None):
    repo = _repo(tmp_path, caller=caller)
    (repo / "PROJECT.md").write_text(MANIFEST.format(extra=extra))
    return repo


def test_a_declared_non_target_with_no_caller_is_not_applicable(tmp_path):
    """ADR-0015: 'a repository that declares itself not-a-target must read
    not-applicable on runner.caller -- never violation.' Without this the
    decision does not survive its own recording: the kit keeps reporting a
    defect, and a standing defect invites a future session to resolve it by
    adding a caller, deciding the scope question by satisfying a checklist."""
    repo = _declaring(
        tmp_path,
        "factory_target: false\nfactory_target_reason: the runner may not maintain itself\n",
    )
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())
    assert result["status"] == "not-applicable"
    assert "the runner may not maintain itself" in result["details"][0]["message"]
    assert result["remediation"] is None


def test_a_declared_non_target_without_a_reason_still_reads_not_applicable(tmp_path):
    repo = _declaring(tmp_path, "factory_target: false\n")
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())
    assert result["status"] == "not-applicable"
    assert "factory_target: false" in result["details"][0]["message"]


def test_declaring_non_target_while_hosting_a_caller_stays_a_violation(tmp_path):
    """The dangerous inverse: dispatchable but not intended. Q1 turns a Q2
    VIOLATION into not-applicable; it never turns a Q2 FAILURE into a pass, and
    hosting a caller is the repository contradicting its own declaration.
    `project-standards` sat in this state for ten days."""
    repo = _declaring(tmp_path, "factory_target: false\n", caller=_caller(PIN))
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "runner.caller-contradicts-declaration"


def test_declaring_target_true_leaves_the_check_unchanged(tmp_path):
    repo = _declaring(tmp_path, "factory_target: true\n")
    assert check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())["status"] == "violation"


def test_a_quoted_false_is_not_a_declaration(tmp_path):
    """`factory_target: "false"` is a string. Reading it as a declaration would
    silently excuse a repository on a typo, so it reads as nothing declared and
    the check stays where it was; the schema validator FAILs it separately."""
    repo = _declaring(tmp_path, 'factory_target: "false"\n')
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "runner.no-caller"


def test_no_manifest_at_all_leaves_the_check_unchanged(tmp_path):
    repo = _repo(tmp_path, caller=None)
    assert check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())["status"] == "violation"
