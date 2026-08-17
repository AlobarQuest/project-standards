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
# Q2 — can the factory WORK here? Reported, and deliberately NOT folded into
# `admission_passed`. Two reasons, and the first is decisive: `factory.pat_scope`
# is structurally `unknown` for a fine-grained PAT (no API exposes its permission
# set), so an admission that consumed it would be permanently unachievable for
# every repository. The second is that admission is the REPO-side bar -- things a
# repository can fix in its own tree -- while these are estate-side facts owned by
# a settings page on the account holding a PAT, or by an App Brain record. Neither
# is remediable from the repository, so none of them carries a `remediation`
# payload and none reaches the remediation queue.
CAPABILITY_CHECKS = (
    "factory.pat_access",
    "factory.pat_scope",
    "factory.secrets",
    "factory.landing_known",
)

PASS = "pass"
# ADR-0015: a repository that DECLARES itself not a factory target reads
# `not-applicable` on `runner.caller`. That answer must satisfy admission, or the
# declaration would merely rename the failure it exists to retire. The same
# already applies to a check GitHub reports as unavailable on this plan. `unknown`
# stays admission-failing: a check that could not see is not a check that found
# nothing to object to.
ADMISSION_SATISFYING = (PASS, "not-applicable")


def build_result(repo_name: str, checks: list[dict], generated: datetime) -> dict:
    """Assemble the readiness document from per-check dicts.

    Each check dict: {id, status, details, fix, remediation}. A failed
    admission check with a non-None `remediation` payload becomes a queue
    item; settings-only fixes (remediation None) surface in `fix` alone.
    An admission status outside `ADMISSION_SATISFYING` — `violation` and,
    deliberately, `unknown` — fails admission. `CAPABILITY_CHECKS` ride in
    `checks` and never touch `admission_passed` or the queue; see the note on
    that tuple for why.
    """
    by_id = {c["id"]: c for c in checks}
    admission_passed = all(
        by_id[c]["status"] in ADMISSION_SATISFYING for c in ADMISSION_CHECKS if c in by_id
    )
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
        and c["status"] not in ADMISSION_SATISFYING
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
