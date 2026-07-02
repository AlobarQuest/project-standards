from dataclasses import dataclass

TIERS = {"active", "parking"}
STATUSES = {"idea", "in-progress", "active", "archived"}
VERSION_SOURCES = {"package.json", "pyproject", "cargo", "git-tag", "none"}
KNOWN_STANDARDS = {"project", "security", "code", "infra"}
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

    if "foundation" in fm and not isinstance(fm["foundation"], bool):
        findings.append(Finding("FAIL", "bad_type", f"foundation must be a bool, got {fm['foundation']!r}"))

    applicable_standards = fm.get("applicable_standards")
    applicable_standards_valid = False
    if "applicable_standards" in fm:
        if not isinstance(applicable_standards, list) or not all(isinstance(s, str) for s in applicable_standards):
            findings.append(Finding("FAIL", "bad_type",
                                     f"applicable_standards must be a list of strings, got {applicable_standards!r}"))
        else:
            applicable_standards_valid = True
            for item in applicable_standards:
                if item not in KNOWN_STANDARDS:
                    findings.append(Finding("FAIL", "bad_enum",
                                             f"applicable_standards item invalid: {item!r}"))

    if "coolify_resources" in fm:
        coolify_resources = fm["coolify_resources"]
        if not isinstance(coolify_resources, list) or not all(isinstance(s, str) for s in coolify_resources):
            findings.append(Finding("FAIL", "bad_type",
                                     f"coolify_resources must be a list of strings, got {coolify_resources!r}"))

    if fm.get("foundation") is True:
        if not applicable_standards:
            findings.append(Finding("WARN", "foundation_incomplete",
                                     "foundation is true but applicable_standards is missing or empty"))
        elif applicable_standards_valid and "infra" in applicable_standards and not fm.get("coolify_resources"):
            findings.append(Finding("WARN", "foundation_incomplete",
                                     "applicable_standards includes infra but coolify_resources is missing or empty"))

    return findings
