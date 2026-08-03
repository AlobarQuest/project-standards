import json

from portfolio.onboard_checks import (
    check_backlog_hygiene,
    check_dependabot,
    check_protection,
    check_standards_pinned,
)


def test_dependabot_missing_fires(make_repo):
    repo = make_repo("x")
    result = check_dependabot(repo)
    assert result["status"] == "violation"
    assert "code-standards" in result["fix"]


def test_dependabot_present_passes(make_repo):
    repo = make_repo("x", files={".github/dependabot.yml": "version: 2\n"})
    assert check_dependabot(repo)["status"] == "pass"


def _gh_protection(payload, diagnostic=""):
    def gh_read(args):
        return payload, diagnostic

    return gh_read


# The two bodies GitHub actually returns, verbatim from the API on 2026-08-03.
# They are the whole reason this check has four outcomes: collapsing both to
# "no protection" reports a defect a private repo cannot have and cannot fix.
_UNSET = '{"message":"Branch not protected","status":"404"}'
_PLAN_LIMITED = (
    '{"message":"Upgrade to GitHub Pro or make this repository public to enable '
    'this feature.","status":"403"}'
)


def test_protection_absent_fires_report_only():
    result = check_protection("AlobarQuest/x", gh_read=_gh_protection(None, _UNSET))
    assert result["status"] == "violation"
    assert result["remediation"] is None  # Q5: settings fix, never a queue item
    assert "gh api" in result["fix"]


def test_protection_present_passes():
    gh_read = _gh_protection(json.dumps({"required_pull_request_reviews": {}}))
    assert check_protection("AlobarQuest/x", gh_read=gh_read)["status"] == "pass"


def test_protection_unavailable_on_this_plan_is_not_applicable():
    """A private repo on a plan without branch protection has no defect to fix.

    The old check reported `violation` here and attached a `gh api -X PUT`
    remediation that can only 403 in turn. Assert BOTH halves: the status, and
    that the fix does not tell anyone to run the command that cannot work.
    """
    result = check_protection("AlobarQuest/x", gh_read=_gh_protection(None, _PLAN_LIMITED))
    assert result["status"] == "not-applicable"
    assert result["remediation"] is None
    assert "gh api -X PUT" not in result["fix"]
    assert "public" in result["fix"]


def test_protection_unreadable_is_unknown_not_unprotected():
    """A check that cannot see never asserts what it did not observe.

    An auth or network failure must not read as `main is unprotected` -- that
    is the same wrong-direction claim as the plan-limited case, arriving by a
    different route.
    """
    result = check_protection(
        "AlobarQuest/x", gh_read=_gh_protection(None, "gh: could not authenticate")
    )
    assert result["status"] == "unknown"
    assert "could not authenticate" in result["details"][0]["message"]


AGED = "---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: cargo\npurpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n- [ ] (P2) old thing — added 2020-01-01\n"


def test_backlog_aged_item_fires(make_repo):
    repo = make_repo("x", files={"PROJECT.md": AGED, "Cargo.toml": ""})
    result = check_backlog_hygiene(repo)
    assert result["status"] == "violation"


def test_backlog_clean_passes(make_repo):
    repo = make_repo(
        "x",
        files={
            "PROJECT.md": AGED.replace("2020-01-01", "2026-07-01"),
            "Cargo.toml": "",
        },
    )
    assert check_backlog_hygiene(repo)["status"] == "pass"


FRONT = "---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: cargo\npurpose: p\nupdated: 2026-06-25\napplicable_standards:\n  project: '{pin}'\n---\n\n## Backlog\n"


def test_standards_drift_fires(make_repo, standards_env):
    repo = make_repo("x", files={"PROJECT.md": FRONT.format(pin="0.9"), "Cargo.toml": ""})
    result = check_standards_pinned(repo)
    assert result["status"] == "violation"
    assert "0.9" in result["details"][0]["message"]


def test_standards_current_passes(make_repo, standards_env):
    repo = make_repo("x", files={"PROJECT.md": FRONT.format(pin="1.0"), "Cargo.toml": ""})
    assert check_standards_pinned(repo)["status"] == "pass"
