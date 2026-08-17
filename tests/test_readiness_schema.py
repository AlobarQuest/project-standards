import json
from datetime import UTC, datetime
from pathlib import Path

from portfolio.readiness_schema import (
    ADMISSION_CHECKS,
    ADVISORY_CHECKS,
    SCHEMA_VERSION,
    build_result,
)

GENERATED = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def _passing(check_id):
    return {"id": check_id, "status": "pass", "details": [], "fix": None, "remediation": None}


def _failing(check_id, remediation=None):
    return {
        "id": check_id,
        "status": "violation",
        "details": [{"id": f"{check_id}.x", "message": "constructed failure"}],
        "fix": f"fix {check_id}",
        "remediation": remediation,
    }


def _all_passing():
    return [_passing(c) for c in ADMISSION_CHECKS + ADVISORY_CHECKS]


def test_schema_version_string():
    assert SCHEMA_VERSION == "portfolio-readiness/v1"


def test_green_result_shape():
    result = build_result("brain", _all_passing(), GENERATED)
    assert result["schema"] == "portfolio-readiness/v1"
    assert result["repo"] == "brain"
    assert result["admission_passed"] is True
    assert result["certified"] is False
    assert result["certification"] == {"method": "docs-canary/v1", "evidence": None}
    assert result["remediation_queue"] == []
    assert [c["id"] for c in result["checks"]] == list(ADMISSION_CHECKS + ADVISORY_CHECKS)


def test_admission_violation_fails_admission_and_queues():
    checks = _all_passing()
    checks[0] = _failing(ADMISSION_CHECKS[0], remediation={"summary": "make it current"})
    result = build_result("brain", checks, GENERATED)
    assert result["admission_passed"] is False
    assert len(result["remediation_queue"]) == 1
    item = result["remediation_queue"][0]
    assert item["check"] == ADMISSION_CHECKS[0]
    assert item["repo"] == "brain"
    assert item["fix"] == f"fix {ADMISSION_CHECKS[0]}"
    assert item["remediation"] == {"summary": "make it current"}


def test_unknown_admission_status_is_not_green():
    checks = _all_passing()
    checks[1] = {
        "id": ADMISSION_CHECKS[1],
        "status": "unknown",
        "details": [],
        "fix": None,
        "remediation": None,
    }
    result = build_result("brain", checks, GENERATED)
    assert result["admission_passed"] is False


def test_settings_only_failure_has_fix_but_no_queue_item():
    """A failed check with no remediation payload (e.g. a settings fix per Q5)
    contributes its fix text but never a queue item."""
    checks = _all_passing()
    checks[2] = _failing(ADMISSION_CHECKS[2], remediation=None)
    result = build_result("brain", checks, GENERATED)
    assert result["admission_passed"] is False
    assert result["remediation_queue"] == []


def test_advisory_failure_never_affects_admission_or_queue():
    checks = _all_passing()
    checks[-1] = _failing(ADVISORY_CHECKS[-1], remediation={"summary": "x"})
    result = build_result("brain", checks, GENERATED)
    assert result["admission_passed"] is True
    assert result["remediation_queue"] == []


def test_document_matches_published_schema_required_keys():
    schema_path = (
        Path(__file__).resolve().parents[1] / "schema" / "portfolio-readiness.v1.schema.json"
    )
    published = json.loads(schema_path.read_text())
    result = build_result("brain", _all_passing(), GENERATED)
    for key in published["required"]:
        assert key in result
    assert published["properties"]["schema"]["const"] == SCHEMA_VERSION


# --------------------------------------------------------------------------
# not-applicable, and the capability group
# --------------------------------------------------------------------------

from portfolio.readiness_schema import CAPABILITY_CHECKS  # noqa: E402


def _status(check_id, status):
    return {"id": check_id, "status": status, "details": [], "fix": "f", "remediation": None}


def test_a_not_applicable_admission_check_satisfies_admission():
    """ADR-0015's declaration must retire the finding, not rename it: if
    not-applicable still failed admission, a repository declaring itself not a
    factory target would go on reporting a failure with a different word on it.
    """
    checks = _all_passing()
    checks[ADMISSION_CHECKS.index("runner.caller")] = _status("runner.caller", "not-applicable")
    assert build_result("factory-runner", checks, GENERATED)["admission_passed"] is True


def test_not_applicable_never_queues_remediation():
    checks = _all_passing()
    checks[0] = {
        "id": ADMISSION_CHECKS[0],
        "status": "not-applicable",
        "details": [],
        "fix": "f",
        "remediation": {"summary": "should not be queued"},
    }
    assert build_result("x", checks, GENERATED)["remediation_queue"] == []


def test_unknown_and_violation_still_fail_admission():
    """The other direction, asserted alongside so the loosening is bounded: only
    not-applicable was added, and a check that could not see is still not a
    check that found nothing to object to."""
    for status in ("unknown", "violation"):
        checks = _all_passing()
        checks[0] = _status(ADMISSION_CHECKS[0], status)
        assert build_result("x", checks, GENERATED)["admission_passed"] is False, status


def test_capability_checks_never_touch_admission_or_the_queue():
    """Q2 capability is reported, not admitted on. `factory.pat_scope` is
    structurally unknown for a fine-grained PAT, so an admission consuming it
    would be permanently unachievable for every repository; and these are
    estate-side facts (a settings page, an App Brain record) that no repository
    can remediate in its own tree."""
    checks = _all_passing() + [
        {
            "id": cid,
            "status": "violation",
            "details": [{"id": f"{cid}.x", "message": "m"}],
            "fix": "f",
            "remediation": {"summary": "should not be queued"},
        }
        for cid in CAPABILITY_CHECKS
    ]
    result = build_result("x", checks, GENERATED)
    assert result["admission_passed"] is True
    assert result["remediation_queue"] == []


def test_capability_checks_are_disjoint_from_admission_and_advisory():
    assert not set(CAPABILITY_CHECKS) & set(ADMISSION_CHECKS + ADVISORY_CHECKS)
