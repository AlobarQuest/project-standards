from datetime import date
from pathlib import Path

from . import detect
from .manifest import Manifest, read_manifest, write_manifest

ACTIVE_BODY = "## Backlog\n\n## Future plans\n"
PARKING_BODY = ""


def init_repo(repo: Path, tier: str = "active", today: date | None = None) -> Manifest:
    today = today or date.today()
    existing = read_manifest(repo)
    fm = (
        dict(existing.frontmatter) if existing and "_yaml_error" not in existing.frontmatter else {}
    )
    body = existing.body if existing else (ACTIVE_BODY if tier == "active" else PARKING_BODY)

    fm.setdefault("name", detect.detect_name(repo))
    fm.setdefault("tier", tier)
    fm.setdefault("status", "in-progress")
    fm.setdefault("purpose", detect.detect_purpose(repo) or "TODO: one-line purpose")
    if fm.get("tier") == "active":
        if not fm.get("version"):
            version, source = detect.detect_version(repo)
            fm["version"] = version
            fm.setdefault("version_source", source)
        fm.setdefault("version_source", "none")
        fm.setdefault("updated", today.isoformat())

    m = Manifest(frontmatter=fm, body=body, path=repo / "PROJECT.md")
    write_manifest(m)
    return m
