"""The portfolio feed: what the Mac nightly copies into the factory-events chain.

Every assertion here is about the bytes on disk, because those bytes are the
contract: the nightly copies them verbatim into an append-only chain, and the
work carrier decides from them whether a repository may take work.
"""

import json
import re
import subprocess
from datetime import UTC, datetime, timedelta, timezone

import pytest

from portfolio import config, factory_checks, feed
from portfolio.matrix import PASS, UNKNOWN, VIOLATION
from portfolio.member_scope import MemberRecordUnreadable
from portfolio.onboard_checks import check_runner_caller
from portfolio.scan import scan

# security-standards `schema/factory-event.v1.schema.json`, `timestamp`.
CHAIN_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
MARKER = "MARKER-NOT-A-STATUS"
SCAN_TIME = datetime(2026, 11, 16, 3, 0, 35, tzinfo=UTC)


def _check(check_id, status):
    return {
        "id": check_id,
        "status": status,
        "details": [{"id": f"{check_id}.detail", "message": MARKER}],
        "fix": MARKER,
        "remediation": MARKER,
    }


def _all_checks(status=PASS):
    """What the real sweep returns: `runner.caller` plus the five `FACTORY_CHECKS`."""
    return [_check(i, status) for i in ("runner.caller", *factory_checks.FACTORY_CHECKS)]


def _repo(make_repo, name, origin):
    repo = make_repo(name)
    subprocess.run(["git", "remote", "add", "origin", origin], cwd=repo, check=True)
    return repo


def _sweep(results):
    """A sweep stub keyed by repository NAME, resolved to the paths scan passes."""

    def sweep(repos, _granted):
        return {str(r): results[r.name] for r in repos if r.name in results}

    return sweep


def _feed():
    return json.loads(config.feed_path().read_text())


def test_feed_path_is_beside_portfolio_json(portfolio_env):
    assert config.feed_path() == portfolio_env / "portfolio-feed.json"
    assert config.feed_path().parent == config.json_path().parent


def test_the_feed_holds_the_measured_members_only_with_full_keys_and_four_ids(
    make_repo, portfolio_env
):
    """Two measured members, a member the sweep did not measure, and a non-member."""
    _repo(make_repo, "alpha", "git@github.com:Owner-One/Alpha.git")
    _repo(make_repo, "beta", "https://github.com/owner-two/beta.git")
    _repo(make_repo, "delta", "https://github.com/owner-one/delta")
    stranger = _repo(make_repo, "gamma", "https://github.com/Stranger/gamma.git")
    granted = frozenset({"owner-one/alpha", "owner-two/beta", "owner-one/delta"})
    sweep = _sweep({"alpha": _all_checks(), "beta": _all_checks(VIOLATION)})

    scan(
        roots=[stranger.parent],
        factory_sweep=sweep,
        read_scope=lambda: granted,
        clock=lambda: SCAN_TIME,
    )

    four = dict.fromkeys(feed.FEED_CHECKS)
    assert _feed()["repositories"] == [
        {"repository": "owner-one/alpha", "checks": {k: PASS for k in four}},
        {"repository": "owner-two/beta", "checks": {k: VIOLATION for k in four}},
    ]
    assert _feed()["member_record_unreadable"] is None
    assert _feed()["schema"] == "portfolio-feed.v1"
    assert MARKER not in config.feed_path().read_text()


def test_a_sweep_key_whose_origin_names_no_member_gets_no_row(make_repo, portfolio_env):
    """Members only, even if a sweep returned a row for something else."""
    member = _repo(make_repo, "alpha", "https://github.com/owner-one/alpha.git")
    _repo(make_repo, "gamma", "https://github.com/stranger/gamma.git")
    make_repo("no-origin")
    sweep = _sweep({n: _all_checks() for n in ("alpha", "gamma", "no-origin")})

    scan(
        roots=[member.parent],
        factory_sweep=sweep,
        read_scope=lambda: frozenset({"owner-one/alpha"}),
        clock=lambda: SCAN_TIME,
    )

    assert [r["repository"] for r in _feed()["repositories"]] == ["owner-one/alpha"]


def test_a_check_the_sweep_did_not_record_is_absent(make_repo, portfolio_env):
    repo = _repo(make_repo, "alpha", "https://github.com/owner-one/alpha.git")
    sweep = _sweep({"alpha": [_check("runner.caller", UNKNOWN)]})

    scan(
        roots=[repo.parent],
        factory_sweep=sweep,
        read_scope=lambda: frozenset({"owner-one/alpha"}),
        clock=lambda: SCAN_TIME,
    )

    assert _feed()["repositories"] == [
        {"repository": "owner-one/alpha", "checks": {"runner.caller": UNKNOWN}}
    ]


def test_two_working_copies_of_one_repository_keep_only_the_statuses_they_agree_on():
    by_path = {
        "/a/alpha": [_check("runner.caller", PASS), _check("factory.secrets", PASS)],
        "/b/alpha": [_check("runner.caller", VIOLATION), _check("factory.secrets", PASS)],
    }
    text = feed.build_feed(
        SCAN_TIME, None, by_path, frozenset({"owner/alpha"}), slug_of=lambda _p: "Owner/Alpha"
    )
    assert json.loads(text)["repositories"] == [
        {"repository": "owner/alpha", "checks": {"factory.secrets": PASS}}
    ]


def test_an_unreadable_member_record_gives_no_rows_and_says_why(make_repo, portfolio_env):
    repo = _repo(make_repo, "alpha", "https://github.com/owner-one/alpha.git")

    def unreadable():
        raise MemberRecordUnreadable("the orchestrator answered 401 for GET /api/v1/members")

    scan(
        roots=[repo.parent],
        factory_sweep=_sweep({"alpha": _all_checks()}),
        read_scope=unreadable,
        clock=lambda: SCAN_TIME,
    )

    assert _feed()["repositories"] == []
    assert _feed()["member_record_unreadable"] == (
        "the orchestrator answered 401 for GET /api/v1/members"
    )
    portfolio = json.loads(config.json_path().read_text())
    assert _feed()["member_record_unreadable"] == portfolio["member_record_unreadable"]


def test_scanned_at_is_the_injected_instant_in_utc_whole_seconds(make_repo, portfolio_env):
    repo = make_repo("alpha")
    eastern = timezone(timedelta(hours=-5))
    moment = datetime(2026, 11, 15, 22, 0, 35, 987654, tzinfo=eastern)

    scan(roots=[repo.parent], read_scope=frozenset, clock=lambda: moment)

    scanned_at = _feed()["scanned_at"]
    assert scanned_at == "2026-11-16T03:00:35Z"
    assert CHAIN_TIMESTAMP.match(scanned_at)


def test_a_naive_scan_time_is_refused():
    with pytest.raises(ValueError, match="timezone-aware"):
        feed.format_scanned_at(datetime(2026, 11, 16, 3, 0, 35))


def test_the_same_inputs_write_the_same_bytes(make_repo, portfolio_env):
    _repo(make_repo, "beta", "https://github.com/owner-two/beta.git")
    repo = _repo(make_repo, "alpha", "https://github.com/owner-one/alpha.git")
    granted = frozenset({"owner-one/alpha", "owner-two/beta"})
    # Results in a different order each run, so sorting is what makes the bytes equal.
    runs = [
        {"alpha": _all_checks(), "beta": _all_checks(VIOLATION)},
        {"beta": list(reversed(_all_checks(VIOLATION))), "alpha": list(reversed(_all_checks()))},
    ]
    written = []
    for results in runs:

        def sweep(repos, _granted, results=results):
            by_name = {r.name: str(r) for r in repos}
            return {by_name[name]: checks for name, checks in results.items()}

        scan(
            roots=[repo.parent],
            factory_sweep=sweep,
            read_scope=lambda: granted,
            clock=lambda: SCAN_TIME,
        )
        written.append(config.feed_path().read_bytes())

    assert written[0] == written[1]
    assert [r["repository"] for r in _feed()["repositories"]] == [
        "owner-one/alpha",
        "owner-two/beta",
    ]


def test_a_failed_write_raises_and_leaves_the_earlier_feed_whole(
    make_repo, portfolio_env, monkeypatch
):
    repo = make_repo("alpha")
    config.feed_path().write_text("earlier feed\n")

    def fail(_src, _dst):
        raise OSError("disk full")

    monkeypatch.setattr(feed.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        scan(roots=[repo.parent], read_scope=frozenset, clock=lambda: SCAN_TIME)

    assert config.feed_path().read_text() == "earlier feed\n"
    assert sorted(p.name for p in portfolio_env.iterdir()) == [
        "PORTFOLIO.md",
        "portfolio-feed.json",
        "portfolio.json",
    ]


def test_a_failed_first_write_leaves_no_feed(make_repo, portfolio_env, monkeypatch):
    repo = make_repo("alpha")

    def fail(_src, _dst):
        raise OSError("disk full")

    monkeypatch.setattr(feed.os, "replace", fail)
    with pytest.raises(OSError):
        scan(roots=[repo.parent], read_scope=frozenset, clock=lambda: SCAN_TIME)

    assert sorted(p.name for p in portfolio_env.iterdir()) == ["PORTFOLIO.md", "portfolio.json"]


def test_every_feed_check_is_one_the_sweep_can_emit(tmp_path):
    """A renamed check must fail here rather than vanish from the feed."""
    assert set(feed.FEED_CHECKS) - {"runner.caller"} <= set(factory_checks.FACTORY_CHECKS)
    unreachable = check_runner_caller(
        tmp_path, "owner/repo", gh=lambda _args: None, gh_read=lambda _args: (None, "offline")
    )
    assert unreachable["id"] in feed.FEED_CHECKS
