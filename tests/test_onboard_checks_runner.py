import base64
import json
from pathlib import Path

import pytest

from portfolio.onboard_checks import (
    CALLER_PATH,
    check_runner_caller,
    declared_pin,
    required_secrets,
)

FIXTURE_WORKFLOW = (Path(__file__).parent / "fixtures" / "factory-runner-workflow.yml").read_text()
PIN = "f1cf3c57c74920c0adb4d03c9828d876198d619e"
SLUG = "AlobarQuest/repo"
SECRETS = [
    "FACTORY_RUNNER_TOKEN",
    "FACTORY_RUNNER_CREDENTIAL_KEY_ID",
    "ANTHROPIC_API_KEY",
    "FACTORY_PR_TOKEN",
]
NOT_FOUND = "gh: Not Found (HTTP 404)\n"


def _caller(pin):
    return (
        "name: Factory Runner Pilot\n"
        "jobs:\n"
        "  factory-runner:\n"
        f"    uses: AlobarQuest/factory-runner/.github/workflows/factory-runner.yml@{pin}\n"
    )


DECLARATION = 'factory_target = {value}\nfactory_target_reason = "{reason}"\n'
TARGET = DECLARATION.format(value="true", reason="a target")


def _repo(tmp_path, **_ignored):
    """A working copy. It contributes PATHS to the fix text and nothing else.

    Since 2026-09-12 `runner.caller` judges the REMOTE, so the tree here is
    deliberately empty: a test that seeded a caller into it and passed would be
    measuring the defect this check was moved to the remote to retire.
    """
    repo = tmp_path / "repo"
    (repo / ".github" / "workflows").mkdir(parents=True)
    return repo


def _fake_gh(pin=PIN, workflow=FIXTURE_WORKFLOW, secret_names=SECRETS, fail_on=()):
    """factory-runner's pin and workflow, and the target's secret names."""

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


def _fake_remote(caller=None, declaration=TARGET, visible=True, fail_on=()):
    """The repository AS GITHUB SERVES IT, in the `gh_read` shape.

    `declaration` defaults to a target: since 2026-09-11 an absent
    `factory-target.toml` means NOT a target, so a fixture declaring nothing
    would send every caller/pin/secret case below down the not-a-target branch
    and stop them testing what they are named for.
    """
    files = {}
    if caller is not None:
        files[CALLER_PATH] = caller
    if declaration is not None:
        files["factory-target.toml"] = declaration

    def gh_read(args):
        path = args[-1]
        for needle in fail_on:
            if needle in path:
                return None, "gh: connection reset\n"
        if not visible:
            # GitHub hides rather than 403s, so an invisible repository answers
            # 404 to EVERY path under it -- including the contents reads, which
            # is what makes a bare contents 404 ambiguous in the first place.
            return None, NOT_FOUND
        if path == f"repos/{SLUG}":
            return json.dumps({"full_name": SLUG}), ""
        prefix = f"repos/{SLUG}/contents/"
        assert path.startswith(prefix), f"unexpected gh_read args: {args}"
        name = path[len(prefix) :]
        if name not in files:
            return None, NOT_FOUND
        return json.dumps({"content": base64.b64encode(files[name].encode()).decode()}), ""

    return gh_read


def _check(tmp_path, *, caller=None, declaration=TARGET, gh=None, **remote):
    return check_runner_caller(
        _repo(tmp_path),
        SLUG,
        gh=gh or _fake_gh(),
        gh_read=_fake_remote(caller=caller, declaration=declaration, **remote),
    )


def test_declared_pin_reads_marker():
    assert declared_pin(gh=_fake_gh()) == PIN


def test_required_secrets_from_workflow_at_sha():
    assert required_secrets(PIN, gh=_fake_gh()) == set(SECRETS)


# --------------------------------------------------------------------------
# The check judges the REMOTE, never the working copy
# --------------------------------------------------------------------------


def test_a_stale_checkout_of_a_conformant_repository_passes(tmp_path):
    """The defect this check was moved to the remote to retire, 2026-09-12.

    `brain` held `18f6355c` and no `factory-target.toml` in a checkout three
    commits behind, while its default branch held the declaration and the
    caller at the declared pin. The check read the local file and compared it
    against a pin fetched from GitHub -- local file, remote pin, exact equality
    -- so a checkout that was merely behind reported a repository defect. Three
    of the six repositories the nightly sweep measures read `violation` for that
    reason alone and nothing was wrong with any of them.

    The working copy here carries nothing at all, which is the strongest form of
    the case: whatever a checkout has or lacks must not reach the verdict.
    """
    repo = _repo(tmp_path)
    assert not (repo / "factory-target.toml").exists()
    result = check_runner_caller(
        repo, SLUG, gh=_fake_gh(), gh_read=_fake_remote(caller=_caller(PIN))
    )
    assert result["status"] == "pass"


def test_a_current_checkout_of_an_off_pin_repository_still_violates(tmp_path):
    """The other direction, and the one that says the check still checks.

    A fix that reads the remote everywhere makes every stale checkout green; on
    its own that is indistinguishable from a check that stopped checking. So the
    inverse is pinned too: a working copy that is perfectly conformant cannot
    excuse a default branch that is behind the declared pin. This is the case
    the next increment makes load-bearing, because a `violation` will then
    refuse work rather than print a line.
    """
    repo = _repo(tmp_path)
    (repo / ".github" / "workflows" / "factory-runner-pilot.yml").write_text(_caller(PIN))
    (repo / "factory-target.toml").write_text(TARGET)
    result = check_runner_caller(
        repo, SLUG, gh=_fake_gh(), gh_read=_fake_remote(caller=_caller("a" * 40))
    )
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "runner.behind-pin"


def test_a_local_caller_cannot_satisfy_a_remote_that_has_none(tmp_path):
    """The same inversion one file over: a caller in the tree is not a caller in
    the repository, and only the second can receive a dispatch."""
    repo = _repo(tmp_path)
    (repo / ".github" / "workflows" / "factory-runner-pilot.yml").write_text(_caller(PIN))
    result = check_runner_caller(repo, SLUG, gh=_fake_gh(), gh_read=_fake_remote(caller=None))
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "runner.no-caller"


# --------------------------------------------------------------------------
# What the remote says about the caller
# --------------------------------------------------------------------------


def test_missing_caller_fires_pointing_at_template(tmp_path):
    result = _check(tmp_path, caller=None)
    assert result["status"] == "violation"
    assert "factory-runner-caller.yml" in result["fix"]


def test_main_ref_fires_naming_gap4_class(tmp_path):
    result = _check(tmp_path, caller=_caller("main"))
    assert result["status"] == "violation"
    assert "@main" in result["details"][0]["message"]


def test_behind_declared_pin_fires(tmp_path):
    result = _check(tmp_path, caller=_caller("a" * 40))
    assert result["status"] == "violation"
    assert "declared pin" in result["details"][0]["message"]


def test_missing_secret_fires_naming_it(tmp_path):
    result = _check(tmp_path, caller=_caller(PIN), gh=_fake_gh(secret_names=SECRETS[:-1]))
    assert result["status"] == "violation"
    assert "FACTORY_PR_TOKEN" in result["details"][0]["message"]


def test_conformant_caller_passes(tmp_path):
    assert _check(tmp_path, caller=_caller(PIN))["status"] == "pass"


def test_declared_pin_unreachable_is_unknown_never_green(tmp_path):
    gh = _fake_gh(fail_on=("RECOMMENDED_CALLER_PIN",))
    assert _check(tmp_path, caller=_caller(PIN), gh=gh)["status"] == "unknown"


# --------------------------------------------------------------------------
# A read that failed is UNKNOWN — the spec's binding clause
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["factory-target.toml", CALLER_PATH])
def test_an_unreadable_remote_is_unknown_never_a_repository_defect(tmp_path, path):
    """`2026-08-17-factory-capability-checks-spec.md`: a missing or failing
    credential must produce `unknown`, never `pass` and never `violation` --
    "the fail-open that would make the whole spec decorative". Moving the read
    to the remote is what makes that clause bite here at all: the old check
    could not fail this way because it read a file off the disk, and the price
    of the fix is that an environment without `gh` now cannot see either file.
    `unknown` is the honest answer and it never satisfies admission."""
    result = _check(tmp_path, caller=_caller(PIN), fail_on=(path,))
    assert result["status"] == "unknown"
    assert result["details"][0]["id"].startswith("runner.")
    assert result["remediation"] is None


def test_a_repository_this_reader_cannot_see_is_unknown_not_a_missing_caller(tmp_path):
    """A contents 404 is ambiguous and must not be believed on its own.

    GitHub answers 404 for a file that is not there AND for a repository the
    reader cannot see -- an unauthenticated `gh` against a private repository
    takes the second path. Believing the first reading would report "no caller
    workflow" about a repository whose caller the reader was simply not allowed
    to read, which is the spec's forbidden outcome wearing a plausible message.
    Every factory-adjacent repository is public today, so this branch does not
    fire in the estate; that is why it is pinned here rather than measured."""
    result = _check(tmp_path, caller=_caller(PIN), visible=False)
    assert result["status"] == "unknown"


def test_content_that_does_not_decode_is_unknown_rather_than_an_absent_file(tmp_path):
    """The last way an absence can be manufactured, and the one a mutation run
    found unpinned: GitHub answered, so there is no 404 and no diagnostic, but
    the payload did not decode. Reading that as "the file is not there" reports
    `runner.no-caller` about a repository that has one — the spec's forbidden
    outcome reached through the success path rather than the failure path."""

    def gh_read(args):
        if args[-1].endswith("factory-target.toml"):
            return json.dumps({"content": base64.b64encode(TARGET.encode()).decode()}), ""
        return json.dumps({"content": "not base64 at all !!"}), ""

    result = check_runner_caller(_repo(tmp_path), SLUG, gh=_fake_gh(), gh_read=gh_read)
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "runner.caller-unreachable"


def test_a_transient_failure_is_not_turned_into_an_absence_by_the_probe(tmp_path):
    """The 404 test comes FIRST, before the repository probe.

    Probing the repository to disambiguate is only sound for a read that
    actually 404ed. A network blip on the contents call followed by a repository
    read that succeeds a moment later would otherwise be reported as "the file
    is absent" -- a violation manufactured out of a transient, which is the
    exact class this change exists to remove."""
    result = _check(tmp_path, caller=_caller(PIN), fail_on=(CALLER_PATH,))
    assert result["status"] == "unknown"
    assert "connection reset" in result["details"][0]["message"]


# --------------------------------------------------------------------------
# ADR-0015: Q2's one read of Q1
# --------------------------------------------------------------------------


def test_a_declared_non_target_with_no_caller_is_not_applicable(tmp_path):
    """ADR-0015: 'a repository that declares itself not-a-target must read
    not-applicable on runner.caller -- never violation.' Without this the
    decision does not survive its own recording: the kit keeps reporting a
    defect, and a standing defect invites a future session to resolve it by
    adding a caller, deciding the scope question by satisfying a checklist."""
    result = _check(
        tmp_path,
        declaration=DECLARATION.format(value="false", reason="the runner may not maintain itself"),
    )
    assert result["status"] == "not-applicable"
    assert "the runner may not maintain itself" in result["details"][0]["message"]
    assert result["remediation"] is None


def test_a_stale_checkout_does_not_hide_a_declaration_the_repository_made(tmp_path):
    """`factory-runner` on 2026-09-12: its default branch declares
    `factory_target = false` with ADR-0015's reasoning, and the checkout was
    three commits behind and had no file at all. The old check answered
    not-applicable for the RIGHT verdict on the WRONG basis -- 'no
    factory-target.toml, absence means not a target' -- and it is that stand-in
    reason, not the status, that reaches `PORTFOLIO.md` for a human to read."""
    result = _check(
        tmp_path,
        declaration=DECLARATION.format(value="false", reason="the runner may not maintain itself"),
    )
    assert "absence means not a factory target" not in result["details"][0]["message"]


def test_no_declaration_and_no_caller_is_not_applicable(tmp_path):
    """The case that moves, 2026-09-11: absence of `factory-target.toml` means
    NOT a target, so a repository that never opted in stops being reported as
    defective for it. Before this, an undeclared repository with no caller read
    `violation` / `runner.no-caller` -- the standing defect ADR-0015 was written
    against, left in place for every repository that had not declared."""
    result = _check(tmp_path, declaration=None)
    assert result["status"] == "not-applicable"
    assert result["details"][0]["id"] == "runner.not-a-factory-target"
    assert "absence means not a factory target" in result["details"][0]["message"]


def test_no_declaration_while_hosting_a_caller_is_a_violation(tmp_path):
    """Under absence-means-no a repository hosting a caller is dispatchable
    while nothing says it is meant to be, which is a violation -- but NOT the
    same violation as an explicit `false` beside a caller. Those two want
    opposite remedies, and the sibling test below is where that difference is
    pinned; here the point is only that silence plus a caller is reported at
    all, and that the message names the absent file rather than a declaration
    nobody wrote."""
    result = _check(tmp_path, caller=_caller(PIN), declaration=None)
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "runner.caller-contradicts-declaration"
    assert "has no factory-target.toml" in result["details"][0]["message"]


def test_silence_beside_a_caller_asks_for_a_declaration_rather_than_a_deletion(tmp_path):
    """The two ways of not being a target want OPPOSITE remedies, and only the
    message distinguished them at first.

    A repository that DECLARED `false` and kept its caller has answered, so the
    caller is the thing that is wrong -- delete it. A repository that declared
    NOTHING has not answered, and the estate cannot know which way it goes, so
    telling it to delete its caller de-onboards it on the strength of a file
    nobody wrote. `remediation` is the half that matters: a failed admission
    check with a payload becomes a `remediation_queue` item, and that queue is
    the cross-repo contract `factory create --from-readiness` reads."""
    silent = _check(tmp_path / "silent", caller=_caller(PIN), declaration=None)
    declared = _check(
        tmp_path / "declared",
        caller=_caller(PIN),
        declaration=DECLARATION.format(value="false", reason="decided, not defective"),
    )

    assert silent["status"] == declared["status"] == "violation"
    assert silent["remediation"] == {
        "summary": "declare whether this repository is a factory target"
    }
    assert declared["remediation"] == {
        "summary": "remove the caller workflow from a declared non-target"
    }
    assert "delete" not in silent["fix"].split("or")[0]
    assert declared["fix"].startswith("delete ")


def test_declaring_non_target_while_hosting_a_caller_stays_a_violation(tmp_path):
    """The dangerous inverse: dispatchable but not intended. Q1 turns a Q2
    VIOLATION into not-applicable; it never turns a Q2 FAILURE into a pass, and
    hosting a caller is the repository contradicting its own declaration.
    `project-standards` sat in this state for ten days."""
    result = _check(
        tmp_path,
        caller=_caller(PIN),
        declaration=DECLARATION.format(value="false", reason="decided, not defective"),
    )
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "runner.caller-contradicts-declaration"
    assert "declares factory_target = false" in result["details"][0]["message"]


def test_declaring_target_true_leaves_the_check_unchanged(tmp_path):
    assert _check(tmp_path, declaration=TARGET)["status"] == "violation"


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
    result = _check(tmp_path, declaration=body)
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "runner.declaration-unreadable"


def test_an_unreadable_declaration_beats_the_caller_check(tmp_path):
    """Order matters: the declaration is read first, so a repository that both
    hosts a caller and carries a broken declaration reads `unknown` rather than
    `pass`. A conformant caller must not paper over a declaration nobody can
    read -- that is the shape where a repository is dispatchable and the file
    that decides whether it should be says nothing legible."""
    result = _check(tmp_path, caller=_caller(PIN), declaration="factory_target = 1\n")
    assert result["status"] == "unknown"
