import base64
import json
from pathlib import Path

import pytest

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


DECLARATION = 'factory_target = {value}\nfactory_target_reason = "{reason}"\n'


def _repo(tmp_path, caller=None, declaration=DECLARATION.format(value="true", reason="a target")):
    """A repository that declares itself a factory target unless told otherwise.

    The default is load-bearing: since 2026-09-11 an ABSENT `factory-target.toml`
    means not a target, so a fixture that declared nothing would send every
    caller/pin/secret case below down the not-a-target branch and stop them
    testing what they are named for.
    """
    repo = tmp_path / "repo"
    (repo / ".github" / "workflows").mkdir(parents=True)
    if caller is not None:
        (repo / ".github" / "workflows" / "factory-runner-pilot.yml").write_text(caller)
    if declaration is not None:
        (repo / "factory-target.toml").write_text(declaration)
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


def test_a_declared_non_target_with_no_caller_is_not_applicable(tmp_path):
    """ADR-0015: 'a repository that declares itself not-a-target must read
    not-applicable on runner.caller -- never violation.' Without this the
    decision does not survive its own recording: the kit keeps reporting a
    defect, and a standing defect invites a future session to resolve it by
    adding a caller, deciding the scope question by satisfying a checklist."""
    repo = _repo(
        tmp_path,
        declaration=DECLARATION.format(value="false", reason="the runner may not maintain itself"),
    )
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())
    assert result["status"] == "not-applicable"
    assert "the runner may not maintain itself" in result["details"][0]["message"]
    assert result["remediation"] is None


def test_no_declaration_and_no_caller_is_not_applicable(tmp_path):
    """The case that moves, 2026-09-11: absence of `factory-target.toml` means
    NOT a target, so a repository that never opted in stops being reported as
    defective for it. Before this, an undeclared repository with no caller read
    `violation` / `runner.no-caller` -- the standing defect ADR-0015 was written
    against, left in place for every repository that had not declared."""
    repo = _repo(tmp_path, declaration=None)
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())
    assert result["status"] == "not-applicable"
    assert result["details"][0]["id"] == "runner.not-a-factory-target"
    assert "absence means not a factory target" in result["details"][0]["message"]


def test_no_declaration_while_hosting_a_caller_is_a_violation(tmp_path):
    """`orchestrator`'s live shape as of 2026-09-11: it hosts a caller at the
    pin and is not in the dispatch allowlist. Under absence-means-no that is
    the same contradiction as an explicit `false` beside a caller -- the
    repository is dispatchable and nothing says it is meant to be -- so it
    reads the same way, and the MESSAGE names the absent file rather than a
    declaration nobody wrote."""
    repo = _repo(tmp_path, caller=_caller(PIN), declaration=None)
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "runner.caller-contradicts-declaration"
    assert "has no factory-target.toml" in result["details"][0]["message"]


def test_declaring_non_target_while_hosting_a_caller_stays_a_violation(tmp_path):
    """The dangerous inverse: dispatchable but not intended. Q1 turns a Q2
    VIOLATION into not-applicable; it never turns a Q2 FAILURE into a pass, and
    hosting a caller is the repository contradicting its own declaration.
    `project-standards` sat in this state for ten days."""
    repo = _repo(
        tmp_path,
        caller=_caller(PIN),
        declaration=DECLARATION.format(value="false", reason="decided, not defective"),
    )
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "runner.caller-contradicts-declaration"
    assert "declares factory_target = false" in result["details"][0]["message"]


def test_declaring_target_true_leaves_the_check_unchanged(tmp_path):
    repo = _repo(tmp_path, declaration=DECLARATION.format(value="true", reason="a target"))
    assert check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())["status"] == "violation"


@pytest.mark.parametrize(
    "body",
    [
        'factory_target = "false"\nfactory_target_reason = "r"\n',
        "factory_target = false\n",
        "factory_target: false\n",
    ],
)
def test_an_unreadable_declaration_is_unknown_never_a_pass_or_an_excuse(tmp_path, body):
    """A declaration file that exists and cannot be read is neither an opt-in
    nor the deliberate silence of absence. `unknown` never satisfies admission,
    so this fails closed in both directions: the repository is not excused from
    the caller requirement on a typo, and it is not accused of contradicting a
    declaration it may not have meant to make.

    The quoted "false" is the classic one. The reasonless `false` is new: the
    frontmatter era accepted it and reported not-applicable with a stand-in
    message, and a bare `false` becomes folklore the same way a bare `true`
    does. The YAML-shaped third case is what a hand-migrated file looks like."""
    repo = _repo(tmp_path, declaration=body)
    result = check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "runner.declaration-unreadable"


def test_an_unreadable_declaration_beats_the_caller_check(tmp_path):
    """Order matters: the declaration is read first, so a repository that both
    hosts a caller and carries a broken declaration reads `unknown` rather than
    `pass`. A conformant caller must not paper over a declaration nobody can
    read -- that is the shape where a repository is dispatchable and the file
    that decides whether it should be says nothing legible."""
    repo = _repo(tmp_path, caller=_caller(PIN), declaration="factory_target = 1\n")
    assert check_runner_caller(repo, "AlobarQuest/repo", gh=_fake_gh())["status"] == "unknown"
