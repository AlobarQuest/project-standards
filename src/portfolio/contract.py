"""Parse the foundation_contract block from PROJECT.md frontmatter."""

from dataclasses import dataclass, field

from . import config, exceptions
from .schema import KNOWN_STANDARDS

CONTRACT_VERSION = 1
VERSIONED_STANDARDS = ("project", "code", "security")


@dataclass
class Contract:
    fatal: str | None = None  # unrecognized schema marker — treat all cells unknown
    declared: bool = False  # applicable_standards present, valid, non-empty
    standards: dict = field(default_factory=dict)  # std -> pin (str | None)
    required_checks: list = field(default_factory=list)  # raw entries; wiring validates
    exceptions: list = field(default_factory=list)  # validated entries (Task 2)
    errors: list = field(default_factory=list)  # shape problems (never mask)


def _parse_standards(fm: dict, c: Contract) -> None:
    raw = fm.get("applicable_standards")
    if isinstance(raw, list):
        if raw and all(isinstance(s, str) for s in raw):
            c.standards = {s: None for s in raw}
        elif raw:
            c.errors.append(f"applicable_standards list items must be strings: {raw!r}")
    elif isinstance(raw, dict):
        bad = {
            k: v
            for k, v in raw.items()
            if not isinstance(k, str) or not (v is None or isinstance(v, str))
        }
        if bad:
            c.errors.append(f"applicable_standards pins must be str or null: {bad!r}")
        elif raw:
            c.standards = dict(raw)
    elif raw is not None:
        c.errors.append(f"applicable_standards must be a list or mapping, got {raw!r}")

    unknown = [k for k in c.standards if k not in KNOWN_STANDARDS]
    if unknown:
        c.errors.append(f"unknown standards in applicable_standards: {unknown!r}")
        c.standards = {}
    c.declared = bool(c.standards)


def _parse_checks_and_exceptions(fm: dict, c: Contract) -> None:
    checks = fm.get("required_checks")
    if isinstance(checks, list):
        c.required_checks = checks
    elif checks is not None:
        c.errors.append(f"required_checks must be a list, got {checks!r}")

    raw_exc = fm.get("exceptions")
    if raw_exc is None:
        raw_exc = []
    elif not isinstance(raw_exc, list):
        # isinstance BEFORE any falsy coercion: `exceptions: {}` or `0` must
        # record an error, never silently read as "no exceptions" (T1 review).
        c.errors.append(f"exceptions must be a list, got {raw_exc!r}")
        raw_exc = []
    c.exceptions, exc_errors = exceptions.validate_local(raw_exc)
    c.errors.extend(exc_errors)


def parse_contract(fm: dict) -> Contract:
    c = Contract()
    marker = fm.get("foundation_contract")
    if marker is not None and marker != CONTRACT_VERSION:
        c.fatal = f"foundation_contract must be {CONTRACT_VERSION}, got {marker!r}"
        return c

    _parse_standards(fm, c)
    _parse_checks_and_exceptions(fm, c)
    return c


def current_standard_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for std, repo in config.standards_repos().items():
        try:
            text = (repo / "STANDARD_VERSION").read_text().strip()
        except OSError:
            out[std] = None
            continue
        out[std] = text or None
    return out
