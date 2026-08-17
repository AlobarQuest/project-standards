"""Q2 capability checks.

Two properties are load-bearing across the whole file and are asserted rather
than assumed: a missing credential produces `unknown` and NEVER `pass` or
`violation` (that fail-open would make the check set decorative), and
"App Brain has not assessed this repository" stays distinguishable from "this
process could not ask".
"""

import base64
import json

import pytest

from portfolio import config
from portfolio.factory_checks import (
    FACTORY_CHECKS,
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
