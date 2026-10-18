import re

import pytest

from portfolio.sds_checks import EVIDENCE_PATH
from portfolio.sds_guidance import EXCLUDED, GUIDANCE, OWNERS, REFUSAL_DETAIL_IDS

# The owner table fixed by the spec. Task 10 replaces the id list with the
# checks the command actually runs.
OWNER_TABLE = {
    "repository": (
        "git.current",
        "project.manifest",
        "code.onboarded",
        "ci.executed",
        "security.clean",
        "profile.declared",
        "deps.dependabot",
        "backlog.hygiene",
        "standards.pinned",
        "sds.behavior_evidence",
    ),
    "devon": ("sds.decisions", "factory.pat_access", "factory.app_access"),
    "onboarding": (
        "sds.declaration",
        "runner.caller",
        "sds.cred_inventory",
        "factory.secrets",
        "factory.landing_known",
        "sds.landing_inert",
        "repo.protection",
        "sds.branch_settings",
    ),
}
CHECK_IDS = {check_id for ids in OWNER_TABLE.values() for check_id in ids}

ANTI_GOAL_1 = (
    "Readiness work breaks the functionality or appearance of a website the repository serves."
)


def test_every_check_the_command_runs_has_guidance_or_is_excluded():
    assert CHECK_IDS <= set(GUIDANCE) | set(EXCLUDED)


def test_guidance_covers_exactly_the_owner_table():
    assert set(GUIDANCE) == CHECK_IDS


@pytest.mark.parametrize(
    ("check_id", "owner"),
    [(check_id, owner) for owner, ids in OWNER_TABLE.items() for check_id in ids],
)
def test_each_check_has_the_owner_the_spec_fixes(check_id, owner):
    assert GUIDANCE[check_id].owner == owner


def test_owners_are_the_fixed_three():
    assert OWNERS == ("repository", "devon", "onboarding")
    assert {g.owner for g in GUIDANCE.values()} == set(OWNERS)


def test_pat_scope_is_excluded_and_has_no_guidance():
    assert EXCLUDED == {
        "factory.pat_scope": "structurally unknown for a fine-grained token; step 6's probe tests it"
    }
    assert not set(EXCLUDED) & set(GUIDANCE)


def test_refusal_detail_ids():
    assert REFUSAL_DETAIL_IDS == frozenset({"sds.refused-not-onboarding", "sds.refused-redeploys"})


def test_no_guidance_suggests_a_review_count():
    assert all("required_approving_review_count" not in g.how for g in GUIDANCE.values())


def _fields(guidance):
    return {"why": guidance.why, "done": guidance.done, "how": guidance.how}


@pytest.mark.parametrize("check_id", sorted(CHECK_IDS))
def test_every_field_is_written(check_id):
    for name, text in _fields(GUIDANCE[check_id]).items():
        assert text.strip(), f"{check_id}.{name} is empty"


_BANNED = re.compile(r"\b(should|simply|just|easily)\b|!", re.IGNORECASE)


@pytest.mark.parametrize("check_id", sorted(CHECK_IDS))
def test_prose_follows_the_style_rules(check_id):
    for name, text in _fields(GUIDANCE[check_id]).items():
        assert not _BANNED.search(text), f"{check_id}.{name}: {_BANNED.search(text).group(0)!r}"


# The shape of a BWS machine token: a version digit and dot, then a uuid.
_TOKEN_SHAPE = re.compile(r"\d\.[0-9a-f]{8}-[0-9a-f]{4}-")


@pytest.mark.parametrize("check_id", sorted(CHECK_IDS))
def test_no_field_carries_a_token_shape(check_id):
    for text in _fields(GUIDANCE[check_id]).values():
        assert not _TOKEN_SHAPE.search(text)


@pytest.mark.parametrize("check_id", OWNER_TABLE["onboarding"])
def test_onboarding_checks_say_the_procedure_does_the_work(check_id):
    how = GUIDANCE[check_id].how
    assert "onboarding procedure" in how
    assert re.search(r"runbook step \d", how)


def test_behavior_evidence_states_the_capture_procedure_and_anti_goal():
    how = GUIDANCE["sds.behavior_evidence"].how
    assert ANTI_GOAL_1 in how
    assert EVIDENCE_PATH in how
    for field in (
        "serves_site",
        "baseline_commit",
        "after_commit",
        "unexplained_differences",
        "pages",
        "reason",
    ):
        assert field in how
    for phrase in ("desktop", "phone", "health", "local build", "intended"):
        assert phrase in how


def test_ci_executed_covers_python_and_npm():
    how = GUIDANCE["ci.executed"].how
    assert "uv sync" in how
    assert "dependency group" in how
    assert "npm test" in how


def test_pat_access_is_the_settings_page_procedure():
    how = GUIDANCE["factory.pat_access"].how
    assert "FACTORY_PR_TOKEN" in how
    assert "Repository access" in how
    assert "Workflows" in how


def test_decisions_guidance_shows_the_recorded_format():
    how = GUIDANCE["sds.decisions"].how
    assert "decisions.toml" in how
    assert 'landing = "inert"' in how
