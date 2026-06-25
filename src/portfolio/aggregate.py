import json
import subprocess
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path

from . import config
from .manifest import read_manifest, parse_backlog
from .detect import is_git
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

def _head_date(repo: Path) -> str | None:
    if not is_git(repo):
        return None
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%cs"], cwd=repo,
                             capture_output=True, text=True, timeout=5)
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
        findings = [{"severity": f.severity, "code": f.code, "message": f.message}
                    for f in lint(repo, today=today)]
        head = _head_date(repo)
        stale = False
        if head and fm.get("updated"):
            try:
                gap = (datetime.strptime(head, "%Y-%m-%d").date()
                       - datetime.strptime(str(fm["updated"]), "%Y-%m-%d").date()).days
                stale = gap > config.STALE_DAYS
            except ValueError:
                stale = False
        if stale:                                       # [debate-fix] surface as finding
            findings.append({"severity": "WARN", "code": "stale_manifest",
                             "message": f"{repo.name}: manifest {gap}d behind HEAD"})
        records.append(ProjectRecord(
            name=fm.get("name", repo.name), path=str(repo), tier=fm.get("tier"),
            status=fm.get("status"), version=fm.get("version"), version_source=fm.get("version_source"),
            purpose=fm.get("purpose"), updated=str(fm["updated"]) if fm.get("updated") else None,
            open_backlog=open_count, git=is_git(repo), head_date=head, stale=stale, findings=findings))
    return records

def to_json(records, untriaged_count: int) -> str:
    return json.dumps({"untriaged_count": untriaged_count,
                       "projects": [asdict(r) for r in records]}, indent=2)

def render_digest(records, untriaged_count: int) -> str:
    lines = ["# Portfolio", "", f"Untriaged inbox items: {untriaged_count}", "",
             "| name | tier | version | status | open | stale |",
             "|------|------|---------|--------|------|-------|"]
    for r in sorted(records, key=lambda x: (x.tier or "z", x.name)):
        lines.append(f"| {r.name} | {r.tier or '-'} | {r.version or '-'} | "
                     f"{r.status or '-'} | {r.open_backlog} | {'⚠' if r.stale else ''} |")
    lines += ["", "## Backlog by project", ""]
    for r in sorted(records, key=lambda x: x.name):
        m = read_manifest(Path(r.path))
        items = [i for i in parse_backlog(m.body) if not i.malformed] if m else []
        if items:
            lines.append(f"### {r.name}")
            lines += [f"- {('('+i.priority+') ') if i.priority else ''}{i.text}" for i in items]
            lines.append("")
    return "\n".join(lines) + "\n"
