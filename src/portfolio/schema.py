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


def validate_frontmatter(fm: dict) -> list[Finding]:  # noqa: C901
    findings: list[Finding] = []
    tier = fm.get("tier")
    if tier not in TIERS:
        findings.append(
            Finding("FAIL", "bad_enum", f"tier must be one of {sorted(TIERS)}, got {tier!r}")
        )
        required = REQUIRED_PARKING
    else:
        required = REQUIRED_ACTIVE if tier == "active" else REQUIRED_PARKING
    for field in required:
        if not fm.get(field):
            findings.append(Finding("FAIL", "missing_field", f"missing required field: {field}"))
    if fm.get("status") and fm["status"] not in STATUSES:
        findings.append(Finding("FAIL", "bad_enum", f"status invalid: {fm['status']!r}"))
    if fm.get("version_source") and fm["version_source"] not in VERSION_SOURCES:
        findings.append(
            Finding("FAIL", "bad_enum", f"version_source invalid: {fm['version_source']!r}")
        )

    if "foundation" in fm and not isinstance(fm["foundation"], bool):
        findings.append(
            Finding("FAIL", "bad_type", f"foundation must be a bool, got {fm['foundation']!r}")
        )

    # ADR-0015: being a factory target is DECLARED. A non-bool here (the classic
    # one being a quoted "false") is read as "nothing declared" by
    # manifest.factory_target_declaration, so without this FAIL the declaration
    # would be silently inert -- present in the file, absent in every consumer.
    if "factory_target" in fm and not isinstance(fm["factory_target"], bool):
        findings.append(
            Finding(
                "FAIL", "bad_type", f"factory_target must be a bool, got {fm['factory_target']!r}"
            )
        )

    from .contract import parse_contract  # local import: contract imports KNOWN_STANDARDS

    contract = parse_contract(fm)
    if contract.fatal:
        findings.append(Finding("FAIL", "contract_error", contract.fatal))
    for error in contract.errors:
        findings.append(Finding("FAIL", "contract_error", error))

    if "coolify_resources" in fm:
        coolify_resources = fm["coolify_resources"]
        if not isinstance(coolify_resources, list) or not all(
            isinstance(s, str) for s in coolify_resources
        ):
            findings.append(
                Finding(
                    "FAIL",
                    "bad_type",
                    f"coolify_resources must be a list of strings, got {coolify_resources!r}",
                )
            )

    if fm.get("foundation") is True:
        if not contract.declared:
            findings.append(
                Finding(
                    "WARN",
                    "foundation_incomplete",
                    "foundation is true but applicable_standards is missing or empty",
                )
            )
        elif "infra" in contract.standards and not fm.get("coolify_resources"):
            findings.append(
                Finding(
                    "WARN",
                    "foundation_incomplete",
                    "applicable_standards includes infra but coolify_resources is missing or empty",
                )
            )

    return findings
