import fnmatch
import tomllib
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
