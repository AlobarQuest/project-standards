from datetime import date

from . import config
from .aggregate import build_records, to_json, render_digest
from .inbox import read_inbox

def scan(roots=None, today: date | None = None) -> dict:
    roots = roots or config.DEFAULT_ROOTS
    today = today or date.today()
    records = build_records(roots, today=today)
    untriaged_count = sum(1 for i in read_inbox() if i.status == "untriaged")
    home = config.portfolio_home()
    home.mkdir(parents=True, exist_ok=True)
    config.json_path().write_text(to_json(records, untriaged_count))
    config.digest_path().write_text(render_digest(records, untriaged_count))
    fails = sum(1 for r in records for f in r.findings if f["severity"] == "FAIL")
    warns = sum(1 for r in records for f in r.findings if f["severity"] == "WARN")
    return {"projects": len(records), "fails": fails, "warns": warns}
