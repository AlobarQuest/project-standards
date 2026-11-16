"""The portfolio feed: the four factory check results per member, with the scan's own time.

The Mac nightly copies this file into the factory-events chain as one
`portfolio.scanned` event (orchestrator ADR-0059 Amendment 11), and the moved work
carrier reads that event because its container has no `portfolio.json`. So the
shape is a contract with two other repositories: `FEED_SCHEMA` names it, and a
change to it is a new schema string.

The feed holds statuses only. `details`, `fix` and `remediation` stay in
`portfolio.json`, because the event is copied verbatim into an append-only chain.
"""

import json
import os
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path

from .onboard_checks import repo_slug

FEED_SCHEMA = "portfolio-feed.v1"
FEED_MODE = 0o644

# The work carrier's `CAPABILITY_CHECKS` and `PERMISSION_CHECKS`
# (orchestrator `src/work_carrier/workability.py`), the only results it reads.
FEED_CHECKS = (
    "runner.caller",
    "factory.secrets",
    "factory.landing_known",
    "factory.pat_access",
)


def format_scanned_at(moment: datetime) -> str:
    """`YYYY-MM-DDTHH:MM:SSZ` in UTC: the chain schema's `timestamp` form, whole seconds."""
    if moment.tzinfo is None:
        raise ValueError("the scan time must be timezone-aware; a naive time has no UTC value")
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _statuses(results: list[dict]) -> dict[str, str]:
    return {r["id"]: r["status"] for r in results if r["id"] in FEED_CHECKS}


def _merge(rows: list[dict[str, str]]) -> dict[str, str]:
    """One repository's checks across its working copies: a status they disagree on is dropped.

    Two working copies with one origin are one repository to the reader. Where
    they disagree (`runner.caller` reads the local workflow file), neither answer
    is the repository's, so the check is absent, which the reader takes as unknown.
    """
    first, *rest = rows
    return {
        check: status
        for check, status in first.items()
        if all(row.get(check) == status for row in rest)
    }


def build_feed(
    scanned_at: datetime,
    member_record_unreadable: str | None,
    by_path: Mapping[str, list[dict]],
    granted: frozenset[str],
    slug_of: Callable[[Path], str | None] = repo_slug,
) -> str:
    """The feed document for one scan, as the exact bytes to write.

    The repositories are the sweep's own result keys, and no other: the sweep
    measures a working copy only when its origin names a member. Each key's slug
    is read again from its origin and must still name a granted member, so a key
    whose origin is gone or names no member gets no row (the reader holds a
    record with no row).
    """
    by_slug: dict[str, list[dict[str, str]]] = {}
    for path, results in by_path.items():
        slug = slug_of(Path(path))
        if slug is None or slug.lower() not in granted:
            continue
        by_slug.setdefault(slug.lower(), []).append(_statuses(results))
    document = {
        "schema": FEED_SCHEMA,
        "scanned_at": format_scanned_at(scanned_at),
        "member_record_unreadable": member_record_unreadable,
        "repositories": [
            {"repository": slug, "checks": _merge(rows)} for slug, rows in sorted(by_slug.items())
        ],
    }
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def write_feed(path: Path, text: str) -> None:
    """Replace `path` with `text` atomically, so a reader never sees a half-written feed.

    On failure the temporary file is removed and the error propagates: the scan
    exits non-zero, and any earlier feed is left as it was.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        # mkstemp creates 0600; the feed holds no secret and is read as
        # `portfolio.json` is, so it gets that file's ordinary mode.
        os.chmod(tmp, FEED_MODE)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
