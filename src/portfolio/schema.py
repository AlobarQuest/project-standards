from dataclasses import dataclass

TIERS = {"active", "parking"}
STATUSES = {"idea", "in-progress", "active", "archived"}
VERSION_SOURCES = {"package.json", "pyproject", "cargo", "git-tag", "none"}
REQUIRED_ACTIVE = ["name", "tier", "status", "version", "version_source", "purpose", "updated"]
REQUIRED_PARKING = ["name", "tier", "status", "purpose"]

@dataclass(frozen=True)
class Finding:
    severity: str  # "FAIL" | "WARN"
    code: str
    message: str

def validate_frontmatter(fm: dict) -> list[Finding]:
    findings: list[Finding] = []
    tier = fm.get("tier")
    if tier not in TIERS:
        findings.append(Finding("FAIL", "bad_enum", f"tier must be one of {sorted(TIERS)}, got {tier!r}"))
        required = REQUIRED_PARKING
    else:
        required = REQUIRED_ACTIVE if tier == "active" else REQUIRED_PARKING
    for field in required:
        if not fm.get(field):
            findings.append(Finding("FAIL", "missing_field", f"missing required field: {field}"))
    if fm.get("status") and fm["status"] not in STATUSES:
        findings.append(Finding("FAIL", "bad_enum", f"status invalid: {fm['status']!r}"))
    if fm.get("version_source") and fm["version_source"] not in VERSION_SOURCES:
        findings.append(Finding("FAIL", "bad_enum", f"version_source invalid: {fm['version_source']!r}"))
    return findings
