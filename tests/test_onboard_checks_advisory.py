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


def _gh_protection(payload):
    def gh(args):
        return payload

    return gh


def test_protection_absent_fires_report_only():
    result = check_protection("AlobarQuest/x", gh=_gh_protection(None))
    assert result["status"] == "violation"
    assert result["remediation"] is None  # Q5: settings fix, never a queue item
    assert "gh api" in result["fix"]


def test_protection_present_passes():
    gh = _gh_protection(json.dumps({"required_pull_request_reviews": {}}))
    assert check_protection("AlobarQuest/x", gh=gh)["status"] == "pass"


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
