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
    for i, entry in enumerate(entries):
        for field in REQUIRED_FIELDS:
            value = entry.get(field)
            if not isinstance(value, str) or not value:
                raise ExceptionsError(f"{path}: exception[{i}] missing non-empty field {field!r}")
    return entries

def matches(entry: dict, repo: str, standard: str, finding_id: str) -> bool:
    return (entry["repo"] == repo and entry["standard"] == standard
            and fnmatch.fnmatch(finding_id, entry["finding"]))
