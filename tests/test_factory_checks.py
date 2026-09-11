"""Q2 capability checks.

Two properties are load-bearing across the whole file and are asserted rather
than assumed: a missing credential produces `unknown` and NEVER `pass` or
`violation` (that fail-open would make the check set decorative), and
"App Brain has not assessed this repository" stays distinguishable from "this
process could not ask".
"""

import base64
import json
import subprocess

import pytest

from portfolio import config, factory_checks
from portfolio.dispatch_app import AppReach, AppUnreadable
from portfolio.factory_checks import (
    FACTORY_CHECKS,
    REQUIRED_APP_PERMISSIONS,
    check_app_access,
    check_landing_known,
    check_pat_access,
    check_pat_scope,
    check_secrets,
    in_q2_scope,
    memoizing_gh,
    run_factory_checks,
    sweep,
)

FRONT = (
    "---\nname: {name}\ntier: active\nstatus: active\nversion: 1.0.0\n"
    "version_source: pyproject\npurpose: p\nupdated: 2026-08-17\n{extra}---\n\n## Backlog\n"
)
PIN = "f1cf3c57c74920c0adb4d03c9828d876198d619e"
FIXTURE_WORKFLOW = None  # loaded lazily below
SECRETS = [
    "FACTORY_RUNNER_TOKEN",
    "FACTORY_RUNNER_CREDENTIAL_KEY_ID",
    "ANTHROPIC_API_KEY",
    "FACTORY_PR_TOKEN",
]


def _workflow():
    from pathlib import Path

    return (Path(__file__).parent / "fixtures" / "factory-runner-workflow.yml").read_text()


def _scoped(make_repo, name="x", profile="dependency-update", extra=""):
    front = FRONT.format(name=name, extra=f"delivery_profile: {profile}\n{extra}")
    return make_repo(name, files={"PROJECT.md": front})


def _unscoped(make_repo, name="y"):
    return make_repo(name, files={"PROJECT.md": FRONT.format(name=name, extra="")})


def _gh_read(payload=None, diagnostic=""):
    def gh_read(_args):
        return payload, diagnostic

    return gh_read


def _repo_body(push):
    return json.dumps({"full_name": "AlobarQuest/x", "permissions": {"push": push, "pull": True}})


def _fake_gh(pin=PIN, workflow=None, secret_names=None, fail_on=()):
    workflow = _workflow() if workflow is None else workflow
    secret_names = SECRETS if secret_names is None else secret_names

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


@pytest.fixture
def no_credentials(monkeypatch):
    monkeypatch.delenv(config.FACTORY_PAT_ENV, raising=False)
    monkeypatch.delenv(config.APP_BRAIN_KEY_ENV, raising=False)


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setenv(config.FACTORY_PAT_ENV, "test-pat-value")
    monkeypatch.setenv(config.APP_BRAIN_KEY_ENV, "test-brain-key")


# --------------------------------------------------------------------------
# scope
# --------------------------------------------------------------------------


def test_declaring_a_delivery_profile_puts_a_repo_in_scope(make_repo):
    assert in_q2_scope(_scoped(make_repo)) is True


def test_no_delivery_profile_is_out_of_scope(make_repo):
    assert in_q2_scope(_unscoped(make_repo)) is False


def test_a_non_string_delivery_profile_is_out_of_scope(make_repo):
    """The proxy must be a name, not merely a present key: `delivery_profile:`
    with nothing after it parses as None and would otherwise pull a repository
    into a sweep it never declared for."""
    repo = make_repo("z", files={"PROJECT.md": FRONT.format(name="z", extra="delivery_profile:\n")})
    assert in_q2_scope(repo) is False


def test_a_repo_with_no_manifest_is_out_of_scope(make_repo):
    assert in_q2_scope(make_repo("nomanifest")) is False


def test_out_of_scope_repos_get_not_applicable_on_every_capability_check(
    make_repo, credentials, monkeypatch
):
    monkeypatch.setattr(
        "portfolio.factory_checks._token_gh_read",
        lambda _token: pytest.fail("out-of-scope repo must not reach the network"),
    )
    results = run_factory_checks(_unscoped(make_repo), "AlobarQuest/y", gh=_fake_gh())
    assert [c["id"] for c in results] == list(FACTORY_CHECKS)
    assert {c["status"] for c in results} == {"not-applicable"}


# --------------------------------------------------------------------------
# factory.pat_access
# --------------------------------------------------------------------------


def test_pat_access_without_the_credential_is_unknown_never_pass_or_violation(
    make_repo, no_credentials
):
    result = check_pat_access(_scoped(make_repo), "AlobarQuest/x")
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "factory.pat_access.credential-absent"
    assert config.FACTORY_PAT_ENV in result["details"][0]["message"]


def test_pat_access_404_is_a_violation_naming_the_access_list(make_repo, credentials):
    """A fine-grained PAT reports a repository outside its access list as 404,
    not 403 -- measured 2026-08-17 against AlobarQuest/RentVSBuyGA."""
    gh_read = _gh_read(None, "gh: Not Found (HTTP 404)")
    result = check_pat_access(_scoped(make_repo), "AlobarQuest/x", gh_read=gh_read)
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "factory.pat-no-access"
    assert "access list" in result["fix"]


def test_pat_access_bad_credentials_is_unknown_not_a_repo_defect(make_repo, credentials):
    gh_read = _gh_read(None, '{"message":"Bad credentials"} gh: (HTTP 401)')
    result = check_pat_access(_scoped(make_repo), "AlobarQuest/x", gh_read=gh_read)
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "factory.pat-rejected"


def test_pat_access_with_write_access_passes(make_repo, credentials):
    result = check_pat_access(
        _scoped(make_repo), "AlobarQuest/x", gh_read=_gh_read(_repo_body(True))
    )
    assert result["status"] == "pass"


def test_a_bare_200_on_a_public_repo_is_not_access(make_repo, credentials):
    """THE fail-open this check exists to close.

    Measured 2026-08-17: `GET /repos/anthropics/anthropic-sdk-python` answers
    200 under this estate's FACTORY_PR_TOKEN with `permissions.push: false`,
    because a PUBLIC repository is readable by any valid token whether or not it
    is in the fine-grained access list. Two factory-adjacent repositories here
    are public, so a status-only probe would certify them on a token that cannot
    push.
    """
    result = check_pat_access(
        _scoped(make_repo), "AlobarQuest/x", gh_read=_gh_read(_repo_body(False))
    )
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "factory.pat-read-only"


def test_pat_access_unparseable_body_is_unknown(make_repo, credentials):
    result = check_pat_access(_scoped(make_repo), "AlobarQuest/x", gh_read=_gh_read("not json"))
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "factory.pat-permissions-unreadable"


def test_pat_access_never_echoes_the_token(make_repo, credentials):
    result = check_pat_access(
        _scoped(make_repo),
        "AlobarQuest/x",
        token="s3cret-token",
        gh_read=_gh_read(_repo_body(True)),
    )
    assert "s3cret-token" not in json.dumps(result)


# --------------------------------------------------------------------------
# factory.pat_scope
# --------------------------------------------------------------------------


def test_pat_scope_is_unknown_with_and_without_the_credential_but_for_different_reasons(
    make_repo, monkeypatch
):
    """Both are `unknown`; only one is a statement about GitHub.

    Without the credential nothing was attempted. With it, the capability is
    unobservable in principle -- a fine-grained PAT reports no `x-oauth-scopes`
    header and no API exposes its permission set. Collapsing the two would hide
    which of the operator and GitHub is the reason.
    """
    repo = _scoped(make_repo)
    monkeypatch.delenv(config.FACTORY_PAT_ENV, raising=False)
    absent = check_pat_scope(repo)
    monkeypatch.setenv(config.FACTORY_PAT_ENV, "test-pat-value")
    present = check_pat_scope(repo)
    assert absent["status"] == present["status"] == "unknown"
    assert absent["details"][0]["id"] == "factory.pat_scope.credential-absent"
    assert present["details"][0]["id"] == "factory.pat-scope-unobservable"


def test_pat_scope_never_claims_to_have_measured_anything(make_repo, credentials):
    result = check_pat_scope(_scoped(make_repo))
    assert result["status"] != "pass"
    assert "workflows" in result["fix"]


# --------------------------------------------------------------------------
# factory.secrets
# --------------------------------------------------------------------------


def test_secrets_present_passes_and_says_presence_is_not_sufficiency(make_repo):
    result = check_secrets(_scoped(make_repo), "AlobarQuest/x", gh=_fake_gh())
    assert result["status"] == "pass"
    assert "presence is not sufficiency" in result["details"][0]["message"]


def test_missing_secret_fires_naming_it(make_repo):
    gh = _fake_gh(secret_names=SECRETS[:-1])
    result = check_secrets(_scoped(make_repo), "AlobarQuest/x", gh=gh)
    assert result["status"] == "violation"
    assert "FACTORY_PR_TOKEN" in result["details"][0]["message"]


def test_secrets_required_set_comes_from_the_workflow_not_a_literal(make_repo):
    """A hard-coded list is the recorded trap: the stale documentation template
    passed 2 of 4. Serve a workflow requiring a name nobody hard-codes and the
    check must miss it."""
    workflow = _workflow().replace("ANTHROPIC_API_KEY:", "SOME_NEW_SECRET:")
    gh = _fake_gh(workflow=workflow)
    result = check_secrets(_scoped(make_repo), "AlobarQuest/x", gh=gh)
    assert result["status"] == "violation"
    assert "SOME_NEW_SECRET" in result["details"][0]["message"]


def test_secrets_unreadable_pin_is_unknown(make_repo):
    gh = _fake_gh(fail_on=("RECOMMENDED_CALLER_PIN",))
    result = check_secrets(_scoped(make_repo), "AlobarQuest/x", gh=gh)
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "factory.secrets-pin-unreachable"


def test_secrets_unlistable_is_unknown_not_missing(make_repo):
    gh = _fake_gh(fail_on=("secret list",))
    result = check_secrets(_scoped(make_repo), "AlobarQuest/x", gh=gh)
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "factory.secrets-list-failed"


# --------------------------------------------------------------------------
# factory.landing_known
# --------------------------------------------------------------------------


def test_landing_without_the_key_is_unknown(make_repo, no_credentials):
    result = check_landing_known(_scoped(make_repo), "AlobarQuest/x")
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "factory.landing_known.credential-absent"


@pytest.mark.parametrize("landing", ["redeploys", "inert"])
def test_a_determined_landing_passes(make_repo, credentials, landing):
    result = check_landing_known(
        _scoped(make_repo), "AlobarQuest/x", fetch=lambda _s: {"landing": landing, "reason": None}
    )
    assert result["status"] == "pass"
    assert landing in result["details"][0]["message"]


def test_app_brain_answering_unknown_is_a_violation_not_an_unknown(make_repo, credentials):
    """The estate never assessed this repository. That is a Q2 defect, and
    `security-standards` was in exactly this state as a live factory target on
    2026-08-09. It must not read as "this process could not ask"."""
    result = check_landing_known(
        _scoped(make_repo),
        "AlobarQuest/x",
        fetch=lambda _s: {"landing": "unknown", "reason": "no_app_record"},
    )
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "factory.landing-not-determined"
    assert "no_app_record" in result["details"][0]["message"]


def test_an_unreachable_app_brain_is_unknown_not_a_violation(make_repo, credentials):
    result = check_landing_known(_scoped(make_repo), "AlobarQuest/x", fetch=lambda _s: None)
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "factory.landing-source-unreadable"


def test_an_unrecognised_landing_value_is_unknown_never_the_nearest_match(make_repo, credentials):
    result = check_landing_known(
        _scoped(make_repo), "AlobarQuest/x", fetch=lambda _s: {"landing": "rebuilds"}
    )
    assert result["status"] == "unknown"


def test_the_landing_reader_never_raises(monkeypatch):
    """A malformed APP_BRAIN_URL is an ordinary environment typo, and the
    checker's contract is to report `unknown` rather than raise: a doubled dot
    or an over-long DNS label raises UnicodeError (a ValueError) at IDNA
    encoding, which is neither a URLError nor an OSError."""
    from portfolio.factory_checks import _http_get_json

    for url in ("https://host..example/x", "https://" + "a" * 300 + ".example/x", "not-a-url", ""):
        assert _http_get_json(url, {}) is None


@pytest.mark.parametrize("explicit_env", [False, True])
def test_no_child_this_kit_spawns_is_handed_the_app_private_key(monkeypatch, explicit_env):
    """Scrubbed where children are CREATED, not at one call site.

    `gh`, `git` and the security scanner all reach `checkers._run`, and a scrub
    applied at one call site is a property of that call site rather than of the
    kit — the next caller would not inherit it. Both branches are exercised
    because the inherited-environment case is the one that used to leak.
    """
    from portfolio import checkers

    seen = {}
    monkeypatch.setattr(checkers.subprocess, "run", lambda _cmd, **kw: seen.update(kw) or "result")
    monkeypatch.setenv(config.DISPATCH_APP_KEY_ENV, "a-private-key")
    monkeypatch.setenv("HARMLESS_VAR", "kept")
    checkers._run(
        ["gh", "api", "x"],
        env={"X": "1", config.DISPATCH_APP_KEY_ENV: "k"} if explicit_env else None,
    )
    assert config.DISPATCH_APP_KEY_ENV not in seen["env"]
    assert seen["env"]["X" if explicit_env else "HARMLESS_VAR"] == ("1" if explicit_env else "kept")


def test_the_pat_reader_still_withholds_an_ambient_github_token(monkeypatch):
    """An ambient `GITHUB_TOKEN` answering in the PAT's place would turn "the PAT
    can reach this" into "somebody can reach this"."""
    seen = {}

    def fake_run(cmd, env=None, **_k):
        seen["env"] = env
        return None

    monkeypatch.setattr("portfolio.factory_checks._run", fake_run)
    monkeypatch.setenv("GITHUB_TOKEN", "ambient")
    factory_checks._token_gh_read("the-pat")(["api", "repos/o/r"])
    assert "GITHUB_TOKEN" not in seen["env"]
    assert seen["env"]["GH_TOKEN"] == "the-pat"


# --------------------------------------------------------------------------
# factory.app_access
# --------------------------------------------------------------------------

GRANTED = {
    "actions": "write",
    "contents": "write",
    "metadata": "read",
    "pull_requests": "write",
    "workflows": "write",
}


def _reach(**overrides):
    fields = {
        "permissions": dict(GRANTED),
        "repository_selection": "all",
        "suspended": False,
        "repositories": None,
    }
    fields.update(overrides)
    return lambda: AppReach(**fields)


def test_the_required_app_permissions_are_the_ones_the_call_sites_need():
    """A PIN, because this is a second copy of a fact that lives in another repository.

    Nothing holds `REQUIRED_APP_PERMISSIONS` to the orchestrator's call sites —
    `project-standards` does not depend on it and there is no cross-repo
    fixture — so a widening or a narrowing here would otherwise be silent. Each
    member's derivation is in the comment above the constant; this asserts the
    set, so changing it is a deliberate act with a failing test attached.
    """
    assert REQUIRED_APP_PERMISSIONS == {
        "actions": "write",  # POST .../actions/workflows/{w}/dispatches
        "contents": "write",  # PUT .../pulls/{n}/merge writes to the base branch
        "pull_requests": "write",  # the same merge
        "workflows": "write",  # PUT .../pulls/{n}/update-branch over a workflow head
        "metadata": "read",  # mandatory for every installation
    }


def test_an_installation_that_reaches_everything_passes(make_repo):
    result = check_app_access(_scoped(make_repo), "AlobarQuest/x", reach=_reach())
    assert result["status"] == "pass"
    assert result["details"][0]["id"] == "factory.app-can-reach"


def test_green_says_what_it_cannot_establish(make_repo):
    """A pass here is narrower than it reads, and must say so in its own text."""
    result = check_app_access(_scoped(make_repo), "AlobarQuest/x", reach=_reach())
    message = result["details"][0]["message"]
    assert "administration" in message
    assert "attempting it" in message


def test_an_absent_credential_is_unknown_and_never_violation(make_repo):
    """The fail-open the Q2 spec calls the one that would make it all decorative.

    A kit run in an environment without the App key must not report a
    repository defective. `_no_dispatch_app_key` (conftest) guarantees the
    variable is absent, so this exercises the real default reader.
    """
    result = check_app_access(_scoped(make_repo), "AlobarQuest/x")
    assert result["status"] == "unknown"
    assert result["status"] != "violation"
    assert result["details"][0]["id"] == "factory.app-credential-absent"
    assert config.DISPATCH_APP_KEY_ENV in result["fix"]


def test_an_unreadable_installation_is_unknown_and_carries_its_reason(make_repo):
    unreadable = AppUnreadable("factory.app-installation-unreadable", "HTTP 401", "check the key")
    result = check_app_access(_scoped(make_repo), "AlobarQuest/x", reach=lambda: unreadable)
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "factory.app-installation-unreadable"
    assert result["fix"] == "check the key"


def test_a_suspended_installation_is_a_violation(make_repo):
    """Correct permissions, full reach, and it can mint nothing — so it is a real
    defect that the other terms cannot see."""
    result = check_app_access(_scoped(make_repo), "AlobarQuest/x", reach=_reach(suspended=True))
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "factory.app-suspended"


def test_a_selected_installation_that_omits_this_repository_is_a_violation(make_repo):
    """The narrowing this check exists to notice."""
    result = check_app_access(
        _scoped(make_repo),
        "AlobarQuest/x",
        reach=_reach(repository_selection="selected", repositories=frozenset({"alobarquest/y"})),
    )
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "factory.app-repo-not-granted"
    assert "AlobarQuest/x" in result["details"][0]["message"]


def test_a_selected_installation_that_includes_this_repository_passes(make_repo):
    result = check_app_access(
        _scoped(make_repo),
        "AlobarQuest/X",
        reach=_reach(repository_selection="selected", repositories=frozenset({"alobarquest/x"})),
    )
    assert result["status"] == "pass"
    assert "repository-selected" in result["details"][0]["message"]


def test_an_all_installation_is_not_read_as_reaching_nothing(make_repo):
    """`repository_selection` is the discriminator, NEVER the presence of a list.

    Under `all` there is no list to hold, and a reader keyed on absence would
    turn "reaches everything" into "reaches nothing" — the fail-open shape this
    estate has now found in several vocabularies. This is the control: the same
    empty `repositories` under `selected` is a violation, and under `all` is a
    pass.
    """
    scoped = _scoped(make_repo)
    assert check_app_access(scoped, "AlobarQuest/x", reach=_reach())["status"] == "pass"
    narrowed = _reach(repository_selection="selected", repositories=frozenset())
    assert check_app_access(scoped, "AlobarQuest/x", reach=narrowed)["status"] == "violation"


def test_an_unrecognised_repository_selection_is_unknown(make_repo):
    result = check_app_access(
        _scoped(make_repo), "AlobarQuest/x", reach=_reach(repository_selection="some-new-word")
    )
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "factory.app-selection-unrecognised"


@pytest.mark.parametrize("permission", sorted(GRANTED))
def test_losing_any_required_permission_is_a_violation_that_names_it(make_repo, permission):
    """Every member of the set is load-bearing, one at a time.

    Dropping the whole set at once would pass against a check that looked at
    only one member, so each is removed on its own.
    """
    narrowed = {k: v for k, v in GRANTED.items() if k != permission}
    result = check_app_access(
        _scoped(make_repo), "AlobarQuest/x", reach=_reach(permissions=narrowed)
    )
    assert result["status"] == "violation"
    assert result["details"][0]["id"] == "factory.app-permission-below-need"
    assert permission in result["details"][0]["message"]


def test_a_permission_downgraded_to_read_is_a_violation(make_repo):
    """Present is not sufficient: `contents: read` cannot write the squash commit,
    which is the 403 measured on 2026-08-09."""
    result = check_app_access(
        _scoped(make_repo),
        "AlobarQuest/x",
        reach=_reach(permissions={**GRANTED, "contents": "read"}),
    )
    assert result["status"] == "violation"
    assert "contents (need write, granted read)" in result["details"][0]["message"]


def test_more_than_is_needed_is_not_a_defect(make_repo):
    """Compared by RANK, never by string equality: `admin` satisfies `write`, and
    an equality test would report a repository defective for holding more."""
    result = check_app_access(
        _scoped(make_repo),
        "AlobarQuest/x",
        reach=_reach(permissions={**GRANTED, "contents": "admin"}),
    )
    assert result["status"] == "pass"


def test_a_permission_level_this_build_cannot_rank_is_unknown_not_violation(make_repo):
    """The fail-open's mirror image. Ranking an unrecognised word 0 would report a
    repository defective because GitHub invented a level."""
    result = check_app_access(
        _scoped(make_repo),
        "AlobarQuest/x",
        reach=_reach(permissions={**GRANTED, "contents": "superwrite"}),
    )
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "factory.app-permission-unrankable"
    assert "contents='superwrite'" in result["details"][0]["message"]


def test_reach_and_permissions_are_reported_together(make_repo):
    """Both are narrowed on the SAME settings page, so one hiding the other costs a
    whole round trip to discover the second."""
    both = _reach(
        repository_selection="selected",
        repositories=frozenset({"alobarquest/other"}),
        permissions={**GRANTED, "contents": "read"},
    )
    result = check_app_access(_scoped(make_repo), "AlobarQuest/x", reach=both)
    assert result["status"] == "violation"
    assert {d["id"] for d in result["details"]} == {
        "factory.app-repo-not-granted",
        "factory.app-permission-below-need",
    }


def test_a_measured_violation_outranks_an_unmeasurable_term(make_repo):
    """An unrankable permission must not suppress the fact that the installation
    PROVABLY does not reach this repository — and the unmeasurable term still rides
    along rather than being dropped."""
    mixed = _reach(
        repository_selection="selected",
        repositories=frozenset({"alobarquest/other"}),
        permissions={**GRANTED, "contents": "superwrite"},
    )
    result = check_app_access(_scoped(make_repo), "AlobarQuest/x", reach=mixed)
    assert result["status"] == "violation"
    ids = [d["id"] for d in result["details"]]
    assert "factory.app-repo-not-granted" in ids
    assert "factory.app-permission-unrankable" in ids


def test_a_suspended_installation_says_only_that(make_repo):
    """Total, so nothing else is worth reporting beside it: a suspended installation
    mints no token whatever it is granted and wherever."""
    result = check_app_access(
        _scoped(make_repo),
        "AlobarQuest/x",
        reach=_reach(suspended=True, permissions={"metadata": "read"}),
    )
    assert [d["id"] for d in result["details"]] == ["factory.app-suspended"]


def test_a_permission_value_of_an_unreadable_SHAPE_is_unknown_not_violation(make_repo):
    """The finding a reviewer caught: dropping a non-string value made the checker see
    nothing there, rank it `none`, and emit a violation reading "granted nothing" — a
    verdict about the repository arising from a value this build could not read."""
    result = check_app_access(
        _scoped(make_repo),
        "AlobarQuest/x",
        reach=_reach(permissions={**GRANTED, "contents": {"level": "write"}}),
    )
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "factory.app-permission-unrankable"


def test_a_subject_that_is_not_a_slug_is_unknown_not_a_violation(make_repo):
    """`onboard` measures a repository with no GitHub origin under its bare directory
    name. Matching that against an installation's grant would report the INSTALLATION
    defective for a missing remote — a violation about the wrong subject entirely."""
    result = check_app_access(
        _scoped(make_repo),
        "bare-directory-name",
        reach=_reach(repository_selection="selected", repositories=frozenset({"o/r"})),
    )
    assert result["status"] == "unknown"
    assert result["details"][0]["id"] == "factory.app-subject-not-a-slug"


def test_an_out_of_scope_repo_never_reads_the_installation(make_repo):
    def explode():
        pytest.fail("an out-of-scope repo must not read the App installation")

    result = check_app_access(_unscoped(make_repo), "AlobarQuest/y", reach=explode)
    assert result["status"] == "not-applicable"


def test_run_factory_checks_threads_one_reach_through(make_repo):
    calls = []
    reach = lambda: calls.append(1) or AppReach(dict(GRANTED), "all", False, None)  # noqa: E731
    results = run_factory_checks(_unscoped(make_repo), "AlobarQuest/y", gh=_fake_gh(), reach=reach)
    assert [c["id"] for c in results] == list(FACTORY_CHECKS)
    # out of scope, so the reader is threaded but never called
    assert calls == []


def test_no_reported_id_is_a_substring_of_another():
    """A reported id that CONTAINS another breaks every substring reader.

    The estate's own discriminating tests prove a suppression by asserting a
    kind is absent on one pass and present on the next, and an operator greps
    the nightly digest the same way. An id that is a superstring of another
    satisfies the "present" half on its own name while breaking the "absent"
    half for a reason that has nothing to do with the behaviour under test.
    Checked over the CHECK ids and, separately, over the DETAIL ids: the two are
    different vocabularies, and a detail id derived from a check id
    (`<check>.credential-absent`) legitimately contains it.
    """
    import re
    from pathlib import Path

    source = Path(__file__).parent.parent / "src" / "portfolio"
    text = "\n".join(p.read_text() for p in sorted(source.glob("*.py")))
    detail_ids = set(re.findall(r'"id": "([a-z0-9._-]+)"', text))
    detail_ids |= {m for m in re.findall(r'AppUnreadable\(\s*"([a-z0-9._-]+)"', text)}
    detail_ids |= {m for m in re.findall(r'_unreadable\(\s*\n?\s*"([a-z0-9._-]+)"', text)}
    assert "factory.app-can-reach" in detail_ids  # the scan found this file's ids
    from portfolio.readiness_schema import ADMISSION_CHECKS, ADVISORY_CHECKS, CAPABILITY_CHECKS

    check_ids = set(ADMISSION_CHECKS + ADVISORY_CHECKS + CAPABILITY_CHECKS + FACTORY_CHECKS)
    assert "factory.app_access" in check_ids
    for vocabulary in (check_ids, detail_ids):
        for one in vocabulary:
            for other in vocabulary:
                assert one == other or one not in other, f"{one!r} is a substring of {other!r}"


# --------------------------------------------------------------------------
# sweep
# --------------------------------------------------------------------------


def test_sweep_skips_out_of_scope_repos_entirely(make_repo, credentials):
    scoped, unscoped = _scoped(make_repo, "a"), _unscoped(make_repo, "b")
    result = sweep([scoped, unscoped], gh=_fake_gh())
    assert str(unscoped) not in result


def test_sweep_reports_unknown_when_the_slug_cannot_be_derived(make_repo, credentials):
    repo = _scoped(make_repo, "a")  # git repo with no origin remote
    results = sweep([repo], gh=_fake_gh())[str(repo)]
    assert [c["id"] for c in results] == ["runner.caller", *FACTORY_CHECKS]
    assert {c["status"] for c in results} == {"unknown"}


def test_a_sweep_reads_the_app_installation_once_for_every_repository(
    make_repo, credentials, monkeypatch
):
    """One installation read for the whole sweep, not one per repository.

    The App's reach is an installation-level fact, so asking per repository is N
    identical round trips — and, under a `selected` installation, N minted
    tokens. That is the difference between a check that costs one call a night
    and one that mints three credentials.

    The repositories are given an origin remote deliberately: without one,
    `sweep` takes its no-slug branch and never reaches a check at all, and the
    assertion would hold at zero while measuring nothing. The sibling checks are
    stubbed so this stays about the one property and touches no network.
    """
    calls = []
    repos = []
    for name in ("a", "b", "c"):
        repo = _scoped(make_repo, name)
        subprocess.run(
            ["git", "remote", "add", "origin", f"https://github.com/AlobarQuest/{name}.git"],
            cwd=repo,
            check=True,
        )
        repos.append(repo)
    for stub in ("check_pat_access", "check_secrets", "check_landing_known"):
        monkeypatch.setattr(
            f"portfolio.factory_checks.{stub}",
            lambda *_a, **_k: {"id": "x", "status": "pass", "details": [], "fix": None},
        )
    monkeypatch.setattr(
        "portfolio.factory_checks.check_runner_caller",
        lambda *_a, **_k: {"id": "runner.caller", "status": "pass", "details": [], "fix": None},
    )

    result = sweep(
        repos,
        gh=_fake_gh(),
        reach=lambda: calls.append(1) or AppReach(dict(GRANTED), "all", False, None),
    )

    assert len(result) == 3  # every repository was measured...
    assert all(
        any(c["id"] == "factory.app_access" and c["status"] == "pass" for c in checks)
        for checks in result.values()
    )
    assert len(calls) == 1  # ...off ONE installation read


def test_memoizing_gh_answers_identical_argv_once():
    calls = []

    def gh(args):
        calls.append(list(args))
        return "value"

    cached = memoizing_gh(gh)
    assert cached(["api", "x"]) == "value"
    assert cached(["api", "x"]) == "value"
    assert cached(["api", "y"]) == "value"
    assert calls == [["api", "x"], ["api", "y"]]


def test_memoizing_gh_does_not_cache_a_failure():
    """A cached None turns one transient GitHub blip into every repository in
    the sweep reporting `unknown` for the rest of the night. Observed on the
    first real run: a single failed read of RECOMMENDED_CALLER_PIN unknown-ed
    factory.secrets for every subject."""
    answers = [None, "value"]

    def gh(_args):
        return answers.pop(0)

    cached = memoizing_gh(gh)
    assert cached(["api", "x"]) is None
    assert cached(["api", "x"]) == "value"
