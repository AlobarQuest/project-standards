"""The portfolio-readiness/v1 result document (WS-P2.11).

This module is the AUTHORITATIVE shape of the readiness result — the versioned
cross-repo contract `factory create --from-readiness` (intent-packages)
consumes. The published JSON schema lives at
schema/portfolio-readiness.v1.schema.json. Any breaking change bumps the
version string and both sides in one change-set.
"""

from datetime import datetime

SCHEMA_VERSION = "portfolio-readiness/v1"

ADMISSION_CHECKS = (
    "git.current",
    "project.manifest",
    "code.onboarded",
    "ci.executed",
    "security.clean",
    "runner.caller",
    "profile.declared",
)
ADVISORY_CHECKS = (
    "deps.dependabot",
    "repo.protection",
    "backlog.hygiene",
    "standards.pinned",
)

PASS = "pass"


def build_result(repo_name: str, checks: list[dict], generated: datetime) -> dict:
    """Assemble the readiness document from per-check dicts.

    Each check dict: {id, status, details, fix, remediation}. A failed
    admission check with a non-None `remediation` payload becomes a queue
    item; settings-only fixes (remediation None) surface in `fix` alone.
    Any non-pass admission status — including unknown — fails admission.
    """
    by_id = {c["id"]: c for c in checks}
    admission_passed = all(by_id[c]["status"] == PASS for c in ADMISSION_CHECKS if c in by_id)
    admission_passed = admission_passed and all(c in by_id for c in ADMISSION_CHECKS)
    queue = [
        {
            "check": c["id"],
            "repo": repo_name,
            "fix": c["fix"],
            "remediation": c["remediation"],
        }
        for cid in ADMISSION_CHECKS
        if (c := by_id.get(cid)) is not None
        and c["status"] != PASS
        and c["remediation"] is not None
    ]
    return {
        "schema": SCHEMA_VERSION,
        "repo": repo_name,
        "generated": generated.isoformat(),
        "checks": checks,
        "admission_passed": admission_passed,
        "certified": False,
        "certification": {"method": "docs-canary/v1", "evidence": None},
        "remediation_queue": queue,
    }
