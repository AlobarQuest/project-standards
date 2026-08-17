import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import config
from .detect import is_git
from .manifest import parse_backlog, read_manifest
from .matrix import ACCEPTED, COLUMNS, NA, PASS, SYMBOLS, UNKNOWN, VIOLATION
from .validator import lint


@dataclass
class ProjectRecord:
    name: str
    path: str
    tier: str | None
    status: str | None
    version: str | None
    version_source: str | None
    purpose: str | None
    updated: str | None
    open_backlog: int
    git: bool
    head_date: str | None
    stale: bool
    findings: list[dict]
    compliance: dict = field(default_factory=dict)  # column -> {status, details, note}
    # Q2 capability results for repos in scope; empty for every other repo.
    factory: list[dict] = field(default_factory=list)


def _head_date(repo: Path) -> str | None:
    if not is_git(repo):
        return None
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cs"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (subprocess.SubprocessError, OSError):
        return None


def _iter_repos(roots):
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                yield child


def build_records(roots, today: date | None = None) -> list[ProjectRecord]:
    today = today or date.today()
    records = []
    for repo in _iter_repos(roots):
        m = read_manifest(repo)
        fm = m.frontmatter if (m and "_yaml_error" not in m.frontmatter) else {}
        items = parse_backlog(m.body) if m else []
        open_count = sum(1 for i in items if not i.malformed)
        findings = [
            {"severity": f.severity, "code": f.code, "message": f.message}
            for f in lint(repo, today=today)
        ]
        head = _head_date(repo)
        stale = False
        if head and fm.get("updated"):
            try:
                gap = (
                    datetime.strptime(head, "%Y-%m-%d").date()
                    - datetime.strptime(str(fm["updated"]), "%Y-%m-%d").date()
                ).days
                stale = gap > config.STALE_DAYS
            except ValueError:
                stale = False
        if stale:  # [debate-fix] surface as finding
            findings.append(
                {
                    "severity": "WARN",
                    "code": "stale_manifest",
                    "message": f"{repo.name}: manifest {gap}d behind HEAD",
                }
            )
        records.append(
            ProjectRecord(
                name=fm.get("name", repo.name),
                path=str(repo),
                tier=fm.get("tier"),
                status=fm.get("status"),
                version=fm.get("version"),
                version_source=fm.get("version_source"),
                purpose=fm.get("purpose"),
                updated=str(fm["updated"]) if fm.get("updated") else None,
                open_backlog=open_count,
                git=is_git(repo),
                head_date=head,
                stale=stale,
                findings=findings,
            )
        )
    return records


def to_json(records, untriaged_count: int) -> str:
    return json.dumps(
        {"untriaged_count": untriaged_count, "projects": [asdict(r) for r in records]}, indent=2
    )


def render_digest(records, untriaged_count: int) -> str:
    lines = [
        "# Portfolio",
        "",
        f"Untriaged inbox items: {untriaged_count}",
        "",
        "| name | tier | version | status | open | stale |",
        "|------|------|---------|--------|------|-------|",
    ]
    for r in sorted(records, key=lambda x: (x.tier or "z", x.name)):
        lines.append(
            f"| {r.name} | {r.tier or '-'} | {r.version or '-'} | "
            f"{r.status or '-'} | {r.open_backlog} | {'⚠' if r.stale else ''} |"
        )
    lines += ["", "## Backlog by project", ""]
    for r in sorted(records, key=lambda x: x.name):
        m = read_manifest(Path(r.path))
        items = [i for i in parse_backlog(m.body) if not i.malformed] if m else []
        if items:
            lines.append(f"### {r.name}")
            lines += [f"- {('(' + i.priority + ') ') if i.priority else ''}{i.text}" for i in items]
            lines.append("")
    return "\n".join(lines) + "\n" + render_compliance(records) + render_factory(records)


def _finding_lines(records) -> list[str]:
    """Every non-satisfying compliance cell, NAMED.

    The table above renders a status symbol per cell, and a symbol is not
    something a reader can act on: `brain`'s real answer -- "code: pinned 1.0,
    current 1.1" -- was written into portfolio.json nightly and never reached
    the page a human reads, which is how a predicted breakage went unnoticed for
    four days. Accepted exceptions keep their own section below; these are the
    cells nobody has decided about.
    """
    lines = []
    for record in sorted(records, key=lambda x: x.name):
        for column in COLUMNS:
            cell = record.compliance.get(column)
            if cell is None or cell["status"] not in (VIOLATION, UNKNOWN):
                continue
            reported = [d for d in cell["details"] if not d.get("accepted")]
            if reported:
                lines += [
                    f"- {record.name} / {column} / {d['id']}: {d['message']}" for d in reported
                ]
            elif cell.get("note"):
                lines.append(f"- {record.name} / {column} — {cell['note']}")
    return lines


def render_compliance(records) -> str:
    lines = [
        "## Compliance",
        "",
        "| name | " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * (len(COLUMNS) + 1),
    ]
    for r in sorted(records, key=lambda x: x.name):
        cells = [r.compliance.get(col, {"status": UNKNOWN}) for col in COLUMNS]
        lines.append("| " + r.name + " | " + " | ".join(SYMBOLS[c["status"]] for c in cells) + " |")
    accepted = [
        (r.name, col, d)
        for r in records
        for col, c in r.compliance.items()
        if c["status"] == ACCEPTED
        for d in c["details"]
        if d.get("accepted")
    ]
    findings = _finding_lines(records)
    if findings:
        lines += ["", "### What failed", ""] + findings
    if accepted:
        lines += ["", "### Accepted exceptions in effect", ""]
        lines += [
            f"- {name} / {col} / {d['id']} — {d['exception_reason']}" for name, col, d in accepted
        ]
    return "\n".join(lines) + "\n"


def render_factory(records) -> str:
    """Q2 — can the factory work in each repository that declares a delivery profile?

    Repositories outside that scope are absent rather than rendered as a row of
    dashes: the section answers a question about the repositories that want to
    be factory targets, and padding it with the other fifty-five would bury
    them.

    Every non-passing result names its check id and its detail message. Five
    more status symbols nobody can act on would be five more of the defect this
    section exists to correct.
    """
    scoped = [r for r in sorted(records, key=lambda x: x.name) if r.factory]
    if not scoped:
        return ""
    check_ids = [c["id"] for c in scoped[0].factory]
    lines = [
        "",
        "## Factory capability (Q2)",
        "",
        "Whether the factory CAN work in each repository declaring a delivery profile.",
        "Green means the repository does not fail in a way this estate has already",
        "failed — it is not proof that a dispatch would work.",
        "",
        "| name | " + " | ".join(check_ids) + " |",
        "|" + "---|" * (len(check_ids) + 1),
    ]
    for record in scoped:
        by_id = {c["id"]: c for c in record.factory}
        cells = [
            SYMBOLS[by_id[cid]["status"]] if cid in by_id else SYMBOLS[NA] for cid in check_ids
        ]
        lines.append("| " + record.name + " | " + " | ".join(cells) + " |")
    findings = _factory_finding_lines(scoped)
    if findings:
        lines += ["", "### What failed", ""] + findings
    return "\n".join(lines) + "\n"


def _factory_finding_lines(scoped) -> list[str]:
    """Findings grouped by (check, message), listing the repositories affected.

    One line per repository per finding is the right shape for a defect a
    repository has and the wrong shape for a fact about the estate.
    `factory.pat_scope` is `unknown` for EVERY repository forever -- a
    fine-grained PAT's permission set is not observable -- so ungrouped it
    prints the same paragraph six times a night, which is the noise version of
    the bare-symbol problem this section exists to correct. Grouping keeps the
    check id and its message, which is what makes a finding actionable, and
    collapses the repetition that makes it unread.
    """
    grouped: dict[tuple[str, str, str], list[str]] = {}
    for record in scoped:
        for check in record.factory:
            if check["status"] in (PASS, NA):
                continue
            for detail in check["details"]:
                key = (check["id"], detail["message"], check["fix"] or "")
                grouped.setdefault(key, []).append(record.name)
    lines = []
    for (check_id, message, fix), names in grouped.items():
        lines.append(f"- {check_id} — {', '.join(names)}")
        lines.append(f"  - {message}")
        if fix:
            lines.append(f"  - next: {fix}")
    return lines
