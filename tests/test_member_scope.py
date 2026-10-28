"""The nightly sweep's scope, read from the SDS member record."""

import copy
import io
import json
import urllib.error
from email.message import Message
from pathlib import Path

import pytest

from portfolio import config, member_scope
from portfolio.cli import main
from portfolio.member_scope import MemberRecordUnreadable, granted, read_granted
from portfolio.scan import scan

# The orchestrator's answer to GET /api/v1/members, saved from production on 2026-10-28.
LIVE = json.loads((Path(__file__).parent / "fixtures" / "sds_members.json").read_text())

APP_CHANGES_ON_2026_10_28 = frozenset(
    {
        "alobarquest/brain",
        "alobarquest/change-manager",
        "alobarquest/infraops-mcp-server",
        "alobarquest/intent-packages",
        "alobarquest/orchestrator",
        "alobarquest/project-standards",
        "alobarquest/security-standards",
    }
)


def _record(**overrides):
    body = copy.deepcopy(LIVE)
    for member in body["members"]:
        member.update(overrides.get(member["repository"], {}))
    return body


def test_the_live_record_grants_app_changes_to_seven_repositories():
    assert granted(LIVE) == APP_CHANGES_ON_2026_10_28


def test_a_retired_member_is_not_measured():
    body = _record(**{"AlobarQuest/brain": {"state": "retired"}})
    assert "alobarquest/brain" not in granted(body)


def test_a_withdrawn_grant_is_not_measured():
    body = _record()
    brain = next(m for m in body["members"] if m["repository"] == "AlobarQuest/brain")
    brain["grants"]["app_changes"]["state"] = "withdrawn"
    assert "alobarquest/brain" not in granted(body)


def test_a_record_that_grants_app_changes_to_nobody_is_unreadable():
    """An empty sweep must say so: it is never a quiet night with nothing to report."""
    body = _record()
    for member in body["members"]:
        member["grants"]["app_changes"]["state"] = "not_assessed"
    with pytest.raises(MemberRecordUnreadable, match="to no repository"):
        granted(body)


@pytest.mark.parametrize(
    "body",
    [
        [],
        {},
        {"members": {}},
        {"members": [{"repository": "AlobarQuest/a", "state": "member"}]},
        {"members": [{"repository": "AlobarQuest/a", "state": "member", "grants": {}}]},
        {"members": ["AlobarQuest/a"]},
    ],
)
def test_a_body_that_is_not_the_member_record_is_unreadable(body):
    with pytest.raises(MemberRecordUnreadable, match="not the member record"):
        granted(body)


def test_no_token_is_unreadable_and_nothing_is_fetched():
    def fetch(_url, _token):
        pytest.fail("no token, so nothing may be fetched")

    with pytest.raises(MemberRecordUnreadable, match=config.SDS_OBSERVER_TOKEN_ENV):
        read_granted(fetch=fetch)


def test_the_record_is_read_from_the_configured_orchestrator(monkeypatch):
    monkeypatch.setenv(config.SDS_OBSERVER_TOKEN_ENV, "observer-test-value")
    monkeypatch.setenv("SDS_URL", "https://sds.example/")
    seen = []

    def fetch(url, token):
        seen.append((url, token))
        return LIVE

    assert read_granted(fetch=fetch) == APP_CHANGES_ON_2026_10_28
    assert seen == [("https://sds.example/api/v1/members", "observer-test-value")]


def test_a_refusal_names_the_status(monkeypatch):
    def refuse(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", Message(), io.BytesIO())

    monkeypatch.setattr(member_scope.urllib.request, "urlopen", refuse)
    with pytest.raises(MemberRecordUnreadable, match="answered 401"):
        member_scope._fetch("https://sds.example/api/v1/members", "t")


def test_the_request_names_the_observer_key_and_a_real_user_agent(monkeypatch):
    sent = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    def urlopen(request, timeout):
        sent.update({k.lower(): v for k, v in request.header_items()})
        return Response(json.dumps(LIVE).encode())

    monkeypatch.setattr(member_scope.urllib.request, "urlopen", urlopen)
    assert member_scope._fetch("https://sds.example/api/v1/members", "t") == LIVE
    assert sent["x-credential-key-id"] == "orchestrator-observer"
    assert sent["authorization"] == "Bearer t"
    assert "Python-urllib" not in sent["user-agent"]


# --------------------------------------------------------------------------
# what the scan does with it
# --------------------------------------------------------------------------


def _unreadable():
    raise MemberRecordUnreadable("the orchestrator answered 401 for GET /api/v1/members")


def test_an_unreadable_record_measures_nothing_and_says_why(make_repo, portfolio_env):
    """The discriminating case: a failed read must not look like a clean night."""
    repo = make_repo("a")

    def sweep(_repos, _granted):
        pytest.fail("without the member record nothing may be measured")

    summary = scan(roots=[repo.parent], factory_sweep=sweep, read_scope=_unreadable)
    assert summary["member_record_unreadable"] == (
        "the orchestrator answered 401 for GET /api/v1/members"
    )
    data = json.loads(config.json_path().read_text())
    assert all(project["factory"] == [] for project in data["projects"])


def test_a_readable_record_reaches_the_sweep(make_repo, portfolio_env):
    repo = make_repo("a")
    seen = []

    def sweep(_repos, scope):
        seen.append(scope)
        return {}

    summary = scan(
        roots=[repo.parent], factory_sweep=sweep, read_scope=lambda: frozenset({"alobarquest/a"})
    )
    assert summary["member_record_unreadable"] is None
    assert seen == [frozenset({"alobarquest/a"})]


def test_the_scan_command_exits_3_when_the_record_is_unreadable(make_repo, portfolio_env, capsys):
    """No observer token in the test environment (conftest scrubs it), so the real reader
    refuses before any request."""
    repo = make_repo("a")
    assert main(["scan", "--roots", str(repo.parent)]) == 3
    assert (
        config.SDS_OBSERVER_TOKEN_ENV
        in json.loads(capsys.readouterr().out)["member_record_unreadable"]
    )
