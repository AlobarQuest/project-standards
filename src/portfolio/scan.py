from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from . import compliance, config, factory_checks
from .aggregate import build_records, render_digest, to_json
from .inbox import read_inbox
from .manifest import read_manifest
from .matrix import UNKNOWN, VIOLATION


def _attach_factory(records, sweep) -> int:
    """Attach Q2 capability results, returning the count of non-satisfying ones.

    `not-applicable` is not counted: an ADR-0015 declaration and an out-of-scope
    repository are answers, not findings. `unknown` IS counted -- a capability
    nobody measured is not a capability anybody demonstrated, and the nightly
    run exists because Q2 lapses without the repository changing.
    """
    by_path = sweep([Path(record.path) for record in records])
    findings = 0
    for record in records:
        record.factory = by_path.get(record.path, [])
        findings += sum(1 for c in record.factory if c["status"] in (VIOLATION, UNKNOWN))
    return findings


def scan(
    roots=None,
    today: date | None = None,
    now: datetime | None = None,
    factory_sweep=factory_checks.sweep,
) -> dict:
    roots = roots or config.DEFAULT_ROOTS
    today = today or date.today()
    now = now or datetime.now()
    records = build_records(roots, today=today)
    factory_findings = _attach_factory(records, factory_sweep)

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
    config.json_path().write_text(to_json(records, untriaged_count))
    config.digest_path().write_text(render_digest(records, untriaged_count))
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
    }
