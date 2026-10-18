"""Tests for sds_render: the build handoff, Devon's task list and the summary."""

import re
from pathlib import Path

import pytest

from portfolio.sds_assess import assess
from portfolio.sds_decisions import DECISIONS_FILE, FORMAT, onboarding_dir
from portfolio.sds_guidance import (
    ANTI_GOAL_1,
    ANTI_GOAL_2,
    GUIDANCE,
    SECURITY_SCAN_COMMAND,
)
from portfolio.sds_render import (
    HANDOFF_FILE,
    TASKS_FILE,
    RepoFacts,
    render_handoff,
    render_summary,
    render_tasks,
)

PASS, VIOLATION, UNKNOWN = "pass", "violation", "unknown"

FACTS = RepoFacts(
    name="demo",
    slug="AlobarQuest/demo",
    default_branch="main",
    tooling=("pyproject.toml", "Dockerfile"),
    checkout=Path("/repos/demo"),
)

INSTRUCTION = (
    "Work until `portfolio sds-ready <checkout>` reports no repository work. Merge your own pull "
    "request once the repository's Quality job passes on it and the evidence file records no "
    "unexplained differences."
)


def chk(check_id, status, *details):
    return {
        "id": check_id,
        "status": status,
        "details": [{"id": f"{check_id}.d{i}", "message": m} for i, m in enumerate(details)],
        "fix": f"FIX-SENTINEL-{check_id}",
        "remediation": None,
    }


def refusal(check_id, detail_id, message):
    check = chk(check_id, VIOLATION)
    check["details"] = [{"id": detail_id, "message": message}]
    return check


def verdict(*checks, onboarding_done=()):
    """Every guided check, clean unless overridden; onboarding checks pending unless listed."""
    given = {c["id"]: c for c in checks}
    out = []
    for check_id, g in GUIDANCE.items():
        if check_id in given:
            out.append(given[check_id])
        elif g.owner == "onboarding":
            out.append(chk(check_id, PASS if check_id in onboarding_done else VIOLATION))
        else:
            out.append(chk(check_id, PASS))
    return assess(out)


def owned(owner):
    return [i for i, g in GUIDANCE.items() if g.owner == owner]


ALL_GAPS = verdict(
    *(chk(i, VIOLATION, f"detail for {i}") for i in owned("repository")),
    *(chk(i, VIOLATION, f"detail for {i}") for i in owned("devon")),
)
CLEAN = verdict()
ONBOARDING = owned("onboarding")


def _headings(markdown):
    return [len(m.group(1)) for m in re.finditer(r"^(#+) ", markdown, re.M)]


# -- handoff -----------------------------------------------------------------


def test_handoff_is_deterministic():
    assert render_handoff(FACTS, ALL_GAPS) == render_handoff(FACTS, ALL_GAPS)
    assert "2026" not in render_handoff(FACTS, ALL_GAPS)  # no dates leak in


def test_handoff_carries_anti_goals_and_rerun_command():
    text = render_handoff(FACTS, ALL_GAPS)
    assert INSTRUCTION in text
    assert ANTI_GOAL_1 in text and ANTI_GOAL_2 in text
    assert "Never deploy" in text
    assert "portfolio sds-ready /repos/demo" in text


def test_handoff_states_the_repository_facts():
    text = render_handoff(FACTS, ALL_GAPS)
    for fact in ("demo", "AlobarQuest/demo", "`main`", "/repos/demo", "`pyproject.toml`"):
        assert fact in text


def test_handoff_names_the_standards_by_path():
    text = render_handoff(FACTS, CLEAN)
    assert "~/Developer/code-standards/STANDARDS.md" in text
    assert SECURITY_SCAN_COMMAND in text
    assert "query Code Brain before adding a cross-cutting pattern" in text


def test_handoff_has_one_subsection_per_repository_check_in_verdict_order():
    text = render_handoff(FACTS, ALL_GAPS)
    positions = [text.index(f"### `{c['id']}`") for c in ALL_GAPS.repository]
    assert positions == sorted(positions)
    for check in ALL_GAPS.repository:
        g = GUIDANCE[check["id"]]
        section = text[text.index(f"### `{check['id']}`") :]
        detail = f"- detail for {check['id']}"
        assert section.index(detail) < section.index(g.why) < section.index(g.done)
        assert section.index(g.done) < section.index(g.how)


def test_handoff_carries_no_devon_or_onboarding_check():
    text = render_handoff(FACTS, ALL_GAPS)
    for check_id in owned("devon") + ONBOARDING:
        assert f"`{check_id}`" not in text


def test_handoff_never_renders_a_check_fix_string():
    assert "FIX-SENTINEL" not in render_handoff(FACTS, ALL_GAPS)


def test_handoff_says_when_there_is_no_repository_work():
    assert "no repository work" in render_handoff(FACTS, CLEAN).split("## Repository work")[1]


@pytest.mark.parametrize("v", [ALL_GAPS, CLEAN])
def test_handoff_headings_are_well_formed(v):
    levels = _headings(render_handoff(FACTS, v))
    assert levels.count(1) == 1 and levels[0] == 1
    assert all(b - a <= 1 for a, b in zip(levels, levels[1:], strict=False))


# -- tasks -------------------------------------------------------------------


def test_tasks_name_the_decisions_file_path(portfolio_env):
    text = render_tasks(FACTS, ALL_GAPS)
    assert str(onboarding_dir("demo") / DECISIONS_FILE) in text
    assert f"```toml\n{FORMAT}\n```" in text


def test_tasks_list_each_devon_check_with_its_guidance(portfolio_env):
    text = render_tasks(FACTS, ALL_GAPS)
    for check in ALL_GAPS.devon:
        g = GUIDANCE[check["id"]]
        assert f"## `{check['id']}`" in text
        assert f"- detail for {check['id']}" in text
        assert g.why in text and g.done in text and g.how in text
    for check_id in owned("repository") + ONBOARDING:
        assert f"`{check_id}`" not in text


def test_tasks_never_render_a_check_fix_string(portfolio_env):
    assert "FIX-SENTINEL" not in render_tasks(FACTS, ALL_GAPS)


def test_tasks_omit_the_decisions_path_when_decided(portfolio_env):
    v = verdict(chk("factory.pat_access", VIOLATION, "no push"))
    assert DECISIONS_FILE not in render_tasks(FACTS, v)


def test_tasks_say_when_there_is_nothing_to_do(portfolio_env):
    text = render_tasks(FACTS, CLEAN)
    assert "no tasks" in text
    assert _headings(text) == [1]


def test_tasks_are_deterministic(portfolio_env):
    assert render_tasks(FACTS, ALL_GAPS) == render_tasks(FACTS, ALL_GAPS)


# -- summary -----------------------------------------------------------------

READY_LINE = "Ready to onboard demo. Reply yes to onboard it."
RESUME_LINE = "Onboarding is partly done; reply yes to resume it."


def test_summary_asks_the_question_only_when_ready(portfolio_env):
    assert render_summary(FACTS, CLEAN).endswith(READY_LINE)
    gap = verdict(chk("ci.executed", VIOLATION, "no tests ran"))
    for v in (ALL_GAPS, gap):
        assert not v.ready
        assert "reply yes" not in render_summary(FACTS, v).lower()


def test_summary_says_resume_when_in_progress(portfolio_env):
    v = verdict(onboarding_done=ONBOARDING[:1])
    assert v.ready and v.phase == "in-progress"
    text = render_summary(FACTS, v)
    assert text.endswith(RESUME_LINE)
    assert READY_LINE not in text


def test_summary_says_complete_without_a_question(portfolio_env):
    v = verdict(onboarding_done=ONBOARDING)
    assert v.phase == "complete"
    text = render_summary(FACTS, v)
    assert text.endswith("Onboarding is complete.")
    assert "reply yes" not in text.lower()


def test_summary_first_line_names_the_phase(portfolio_env):
    assert render_summary(FACTS, CLEAN).splitlines()[0] == "demo: not-started"


def test_summary_for_a_refused_verdict_asks_nothing(portfolio_env):
    v = verdict(refusal("sds.decisions", "sds.refused-redeploys", "landing redeploys demo"))
    assert v.refusals and v.devon == () and v.repository == ()
    text = render_summary(FACTS, v)
    assert "landing redeploys demo" in text
    assert "can't be onboarded" in text
    assert "reply yes" not in text.lower()


def test_summary_lists_environment_checks_with_their_guidance(portfolio_env):
    v = verdict(chk("ci.executed", UNKNOWN, "cannot read the run log"))
    text = render_summary(FACTS, v)
    assert "ci.executed" in text and "cannot read the run log" in text
    assert GUIDANCE["ci.executed"].how in text
    assert "reply yes" not in text.lower()


def test_summary_points_at_the_handoff_and_task_files(portfolio_env):
    text = render_summary(FACTS, ALL_GAPS)
    n_repo, n_devon = len(ALL_GAPS.repository), len(ALL_GAPS.devon)
    assert str(onboarding_dir("demo") / HANDOFF_FILE) in text
    assert str(onboarding_dir("demo") / TASKS_FILE) in text
    assert f"Repository work: {n_repo} checks" in text
    assert f"Devon's tasks: {n_devon} checks" in text


def test_summary_omits_empty_sections(portfolio_env):
    text = render_summary(FACTS, CLEAN)
    for absent in (HANDOFF_FILE, TASKS_FILE, "Refused", "Environment"):
        assert absent not in text


def test_summary_marks_each_onboarding_action_in_order(portfolio_env):
    v = verdict(onboarding_done=ONBOARDING[:2])
    text = render_summary(FACTS, v)
    lines = [f"  - {i}: {'done' if i in ONBOARDING[:2] else 'pending'}" for i in ONBOARDING]
    assert "\n".join(lines) in text


def test_summary_is_deterministic_and_never_renders_a_fix_string(portfolio_env):
    v = verdict(chk("ci.executed", UNKNOWN, "x"), chk("git.current", VIOLATION, "y"))
    assert render_summary(FACTS, v) == render_summary(FACTS, v)
    assert "FIX-SENTINEL" not in render_summary(FACTS, v)


# -- style -------------------------------------------------------------------


def test_own_prose_avoids_hedging_words(portfolio_env):
    for text in (render_handoff(FACTS, CLEAN), render_tasks(FACTS, CLEAN)):
        assert not re.search(r"\b(should|simply|just|easily)\b|!", text, re.I)


def test_summary_counts_a_single_check_in_the_singular(portfolio_env):
    v = verdict(chk("ci.executed", VIOLATION, "no tests ran"))
    assert "Repository work: 1 check." in render_summary(FACTS, v)
