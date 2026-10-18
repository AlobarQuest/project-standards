"""Tests for sds_assess: routing check results by owner, phase and refusal."""

import pytest

from portfolio.sds_assess import assess
from portfolio.sds_guidance import EXCLUDED, GUIDANCE

PASS, VIOLATION, UNKNOWN, NA = "pass", "violation", "unknown", "not-applicable"


def chk(check_id, status, detail=None):
    details = [{"id": detail, "message": "m"}] if detail else []
    return {"id": check_id, "status": status, "details": details, "fix": None, "remediation": None}


def ids(owner):
    return [i for i, g in GUIDANCE.items() if g.owner == owner]


def clean_rest(*skip):
    return [chk(i, PASS) for i in GUIDANCE if i not in skip]


def test_all_clean_is_ready_and_complete():
    v = assess(clean_rest())
    assert v.ready and v.phase == "complete"
    assert v.refusals == v.environment == v.repository == v.devon == ()


def test_unknown_never_reaches_the_handoff():
    v = assess([chk("ci.executed", UNKNOWN), *clean_rest("ci.executed")])
    assert v.repository == ()
    assert [c["id"] for c in v.environment] == ["ci.executed"]
    assert not v.ready


def test_half_onboarded_is_in_progress_and_still_ready():
    v = assess(
        [
            chk("sds.declaration", PASS),
            chk("factory.secrets", VIOLATION),
            *clean_rest("sds.declaration", "factory.secrets"),
        ]
    )
    assert v.phase == "in-progress" and v.ready
    assert v.repository == () and v.devon == ()


def test_redeploys_refuses():
    v = assess(
        [chk("sds.decisions", VIOLATION, "sds.refused-redeploys"), *clean_rest("sds.decisions")]
    )
    assert not v.ready
    assert [d["id"] for d in v.refusals] == ["sds.refused-redeploys"]
    assert v.devon == () and v.environment == ()


def test_refusal_on_unknown_check_goes_to_refusals_only():
    v = assess(
        [chk("sds.decisions", UNKNOWN, "sds.refused-not-onboarding"), *clean_rest("sds.decisions")]
    )
    assert len(v.refusals) == 1 and v.environment == () and v.devon == ()


def test_non_refusal_detail_does_not_refuse():
    v = assess([chk("git.current", VIOLATION, "git.dirty"), *clean_rest("git.current")])
    assert v.refusals == () and [c["id"] for c in v.repository] == ["git.current"]
    assert not v.ready


def test_unguided_check_raises():
    with pytest.raises(KeyError):
        assess([chk("no.such.check", PASS)])


def test_pat_scope_is_ignored():
    (excluded,) = EXCLUDED
    v = assess([chk(excluded, UNKNOWN), *clean_rest()])
    assert v.environment == () and v.ready


def test_repository_and_devon_violations_route_by_owner():
    v = assess(
        [
            chk("code.onboarded", VIOLATION),
            chk("factory.pat_access", VIOLATION),
            *clean_rest("code.onboarded", "factory.pat_access"),
        ]
    )
    assert [c["id"] for c in v.repository] == ["code.onboarded"]
    assert [c["id"] for c in v.devon] == ["factory.pat_access"]
    assert not v.ready


def test_not_applicable_is_clean_for_repository_and_devon():
    v = assess(
        [
            chk("code.onboarded", NA),
            chk("factory.pat_access", NA),
            *clean_rest("code.onboarded", "factory.pat_access"),
        ]
    )
    assert v.ready and v.repository == () and v.devon == ()


def test_onboarding_not_applicable_is_not_done():
    v = assess([chk("runner.caller", NA), *clean_rest("runner.caller")])
    assert dict((c["id"], d) for c, d in v.onboarding)["runner.caller"] is False
    assert v.phase == "in-progress" and v.ready


def test_onboarding_lists_every_check_in_input_order_with_done_flag():
    order = list(reversed(ids("onboarding")))
    v = assess([chk(i, VIOLATION if n == 0 else PASS) for n, i in enumerate(order)])
    assert [c["id"] for c, _ in v.onboarding] == order
    assert [d for _, d in v.onboarding] == [False] + [True] * (len(order) - 1)


def test_onboarding_unknown_is_not_done_and_in_environment():
    v = assess([chk("sds.declaration", UNKNOWN), *clean_rest("sds.declaration")])
    assert dict((c["id"], d) for c, d in v.onboarding)["sds.declaration"] is False
    assert [c["id"] for c in v.environment] == ["sds.declaration"]
    assert not v.ready


def test_phase_not_started_when_no_onboarding_check_passes():
    v = assess([chk(i, VIOLATION) for i in ids("onboarding")])
    assert v.phase == "not-started" and v.ready


def test_phase_complete_when_all_onboarding_pass():
    assert assess([chk(i, PASS) for i in ids("onboarding")]).phase == "complete"


def test_tuple_order_follows_input_order():
    order = ["security.clean", "git.current", "code.onboarded"]
    v = assess([chk(i, VIOLATION) for i in order])
    assert [c["id"] for c in v.repository] == order
