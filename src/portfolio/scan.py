from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

from . import compliance, config, factory_checks, member_scope
from .aggregate import build_records, render_digest, to_json
from .feed import build_feed, write_feed
from .inbox import read_inbox
from .manifest import read_manifest
from .matrix import UNKNOWN, VIOLATION


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _attach_factory(records, sweep, granted: frozenset[str]) -> tuple[int, dict]:
    """Attach Q2 capability results; return the count of non-satisfying ones and the sweep result.

    `not-applicable` is not counted: an ADR-0015 declaration and an out-of-scope
    repository are answers, not findings. `unknown` IS counted -- a capability
    nobody measured is not a capability anybody demonstrated, and the nightly
    run exists because Q2 lapses without the repository changing.
    """
    by_path = sweep([Path(record.path) for record in records], granted) if granted else {}
    findings = 0
    for record in records:
        record.factory = by_path.get(record.path, [])
        findings += sum(1 for c in record.factory if c["status"] in (VIOLATION, UNKNOWN))
    return findings, by_path


def scan(
    roots=None,
    today: date | None = None,
    now: datetime | None = None,
    factory_sweep=factory_checks.sweep,
    read_scope=None,
    clock=_utc_now,
) -> dict:
    # The feed's time, taken once before anything is measured. `now` stays the
    # naive local time compliance has always used; the feed needs a UTC instant.
    scanned_at = clock()
    roots = roots or config.DEFAULT_ROOTS
    today = today or date.today()
    now = now or datetime.now()
    records = build_records(roots, today=today)
    # Unreadable means no repository is measured, and the result says why: a run
    # that measured nothing must never read like a run that found nothing.
    try:
        granted, member_record_unreadable = (read_scope or member_scope.read_granted)(), None
    except member_scope.MemberRecordUnreadable as error:
        granted, member_record_unreadable = frozenset(), str(error)
    factory_findings, by_path = _attach_factory(records, factory_sweep, granted)

    pairs = []
    for record in records:
        m = read_manifest(Path(record.path))
        # fm=None only when the manifest is missing; a YAML-error frontmatter is
        # passed through so build_rows can note "frontmatter unreadable".
        pairs.append((Path(record.path), m.frontmatter if m else None))
    rows, _stale = compliance.build_rows(pairs, now, today)
    for record, row in zip(records, rows, strict=True):
        record.compliance = {col: asdict(cell) for col, cell in row.cells.items()}

    untriaged_count = sum(1 for i in read_inbox() if i.status == "untriaged")
    home = config.portfolio_home()
    home.mkdir(parents=True, exist_ok=True)
    config.json_path().write_text(to_json(records, untriaged_count, member_record_unreadable))
    config.digest_path().write_text(
        render_digest(records, untriaged_count, member_record_unreadable)
    )
    # Last, so a failed feed write never costs the two outputs the Mac still reads.
    write_feed(
        config.feed_path(),
        build_feed(scanned_at, member_record_unreadable, by_path, granted),
    )
    fails = sum(1 for r in records for f in r.findings if f["severity"] == "FAIL")
    warns = sum(1 for r in records for f in r.findings if f["severity"] == "WARN")
    compliance_violations = sum(
        1 for r in records for c in r.compliance.values() if c["status"] == VIOLATION
    )
    return {
        "projects": len(records),
        "fails": fails,
        "warns": warns,
        "compliance_violations": compliance_violations,
        "factory_findings": factory_findings,
        "member_record_unreadable": member_record_unreadable,
    }
