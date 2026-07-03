import fnmatch
import tomllib
from datetime import date
from pathlib import Path


class ExceptionsError(Exception): ...

REQUIRED_FIELDS = ("repo", "standard", "finding", "reason", "added")

def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ExceptionsError(f"unparseable TOML in {path}: {e}") from e
    entries = data.get("exception", [])
    if not isinstance(entries, list):
        raise ExceptionsError(f"{path}: 'exception' must be a list of tables, got {type(entries).__name__}")
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ExceptionsError(f"{path}: exception[{i}] must be a table, got {type(entry).__name__}")
        for field in REQUIRED_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value:
                raise ExceptionsError(f"{path}: exception[{i}] missing non-empty field {field!r}")
    return entries

def matches(entry: dict, repo: str, standard: str, finding_id: str) -> bool:
    return (entry["repo"] == repo and entry["standard"] == standard
            and fnmatch.fnmatch(finding_id, entry["finding"]))


LOCAL_STANDARDS = {"project", "security", "code", "infra", "checks"}


def _norm_date(value):
    """YAML parses bare dates to datetime.date; accept date or ISO string."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
        return value
    return None


def validate_local(entries) -> tuple[list[dict], list[str]]:
    """Validate PROJECT.md frontmatter exception entries.

    Returns (valid entries with dates normalized to ISO strings, errors).
    An invalid entry is dropped — it must never mask a finding.
    """
    valid, errors = [], []
    for i, raw in enumerate(entries):
        if not isinstance(raw, dict):
            errors.append(f"exceptions[{i}] must be a mapping, got {type(raw).__name__}")
            continue
        entry = dict(raw)
        problems = []
        for f in ("standard", "finding", "reason"):
            if not isinstance(entry.get(f), str) or not entry[f]:
                problems.append(f"missing non-empty field {f!r}")
        if entry.get("standard") not in LOCAL_STANDARDS:
            problems.append(f"standard must be one of {sorted(LOCAL_STANDARDS)}")
        added = _norm_date(entry.get("added"))
        if added is None:
            problems.append("added must be an ISO date")
        entry["added"] = added
        if "review_by" in entry:
            review_by = _norm_date(entry["review_by"])
            if review_by is None:
                problems.append("review_by must be an ISO date")
            entry["review_by"] = review_by
        if problems:
            errors.append(f"exceptions[{i}]: " + "; ".join(problems))
            continue
        valid.append(entry)
    return valid, errors


def local_matches(entry: dict, standard: str, finding_id: str) -> bool:
    return (entry["standard"] == standard
            and fnmatch.fnmatch(finding_id, entry["finding"]))


def expired(entry: dict, today: date) -> bool:
    review_by = entry.get("review_by")
    return bool(review_by) and date.fromisoformat(review_by) < today
