from dataclasses import dataclass, field, asdict

from . import exceptions

STANDARDS = ["project", "security", "code", "infra"]   # per-repo column order
GOVERNANCE = "governance"                               # machine-scope pseudo-standard
MACHINE = "_machine"                                    # repo key for governance exceptions
PASS, VIOLATION, ACCEPTED, NA, UNKNOWN = (
    "pass", "violation", "accepted-exception", "not-applicable", "unknown")

SYMBOLS = {
    PASS: "✅",
    VIOLATION: "❌",
    ACCEPTED: "⚠ accepted",
    NA: "—",
    UNKNOWN: "?",
}

@dataclass(frozen=True)
class CheckResult:            # raw adapter output, pre-exception resolution
    standard: str
    status: str               # pass | violation | unknown (adapters never emit others)
    details: list = field(default_factory=list)   # [{"id": str, "message": str}, ...]
    note: str | None = None

@dataclass
class Cell:
    status: str
    details: list = field(default_factory=list)
    note: str | None = None

@dataclass
class Row:
    repo: str
    path: str
    cells: dict = field(default_factory=dict)      # standard -> Cell


def na_cell() -> Cell:
    return Cell(NA, [])


def resolve_cell(result: CheckResult, exc: list[dict], repo: str) -> tuple[Cell, set[int]]:
    if result.status in (PASS, UNKNOWN):
        return Cell(result.status, result.details, result.note), set()

    used: set[int] = set()
    details = []
    for detail in result.details:
        detail = dict(detail)
        matched = [idx for idx, entry in enumerate(exc)
                   if exceptions.matches(entry, repo, result.standard, detail["id"])]
        if matched:
            detail["accepted"] = True
            detail["exception_reason"] = exc[matched[0]]["reason"]
            used.update(matched)
        details.append(detail)

    if details and all(d.get("accepted") for d in details):
        status = ACCEPTED
    else:
        status = VIOLATION
    return Cell(status, details, result.note), used


def summarize(rows: list[Row], machine_cell: Cell) -> dict:
    counts = {PASS: 0, VIOLATION: 0, ACCEPTED: 0, NA: 0, UNKNOWN: 0}
    for row in rows:
        for cell in row.cells.values():
            counts[cell.status] += 1
    counts[machine_cell.status] += 1
    return counts


def build_report(rows, machine_cell, summary, unused_exceptions, generated: str) -> dict:
    return {
        "generated": generated,
        "standards": STANDARDS,
        "repos": [
            {
                "repo": row.repo,
                "path": row.path,
                "cells": {std: asdict(row.cells.get(std, na_cell())) for std in STANDARDS},
            }
            for row in rows
        ],
        "machine": {GOVERNANCE: asdict(machine_cell)},
        "summary": summary,
        "unused_exceptions": unused_exceptions,
        "exit_code": 1 if summary.get(VIOLATION, 0) > 0 else 0,
    }


def _cell_symbol(cell: Cell) -> str:
    return SYMBOLS[cell.status]


def render_digest(rows, machine_cell, summary, unused_exceptions, generated: str) -> str:
    lines = ["# Foundation Conformance", ""]
    lines.append(
        f"Generated: {generated} · repos: {len(rows)} · "
        f"violations: {summary.get(VIOLATION, 0)} · unknown: {summary.get(UNKNOWN, 0)}"
    )
    lines.append("")

    header = "| repo | " + " | ".join(STANDARDS) + " |"
    sep = "|" + "---|" * (len(STANDARDS) + 1)
    lines.append(header)
    lines.append(sep)
    for row in rows:
        cells = " | ".join(_cell_symbol(row.cells[std]) if std in row.cells else _cell_symbol(na_cell())
                            for std in STANDARDS)
        lines.append(f"| {row.repo} | {cells} |")
    lines.append("")

    lines.append(f"Machine scope: governance = {_cell_symbol(machine_cell)}")
    lines.append("")

    # Collect entries: (repo, standard, cell) including machine/governance
    entries = [(row.repo, std, row.cells[std]) for row in rows for std in STANDARDS if std in row.cells]
    entries.append((MACHINE, GOVERNANCE, machine_cell))

    def _detail_sections(status: str) -> list[str]:
        sections = []
        for repo, std, cell in entries:
            if cell.status != status:
                continue
            non_accepted = [d for d in cell.details if not d.get("accepted")]
            if not non_accepted:
                continue
            seen: set[tuple[str, str]] = set()
            sub = [f"### {repo} / {std}"]
            for d in non_accepted:
                key = (d["id"], d["message"])
                if key in seen:
                    continue
                seen.add(key)
                sub.append(f"- {d['id']}: {d['message']}")
            sections.append("\n".join(sub))
        return sections

    violation_sections = _detail_sections(VIOLATION)
    if violation_sections:
        lines.append("## Violations")
        lines.append("")
        lines.append("\n\n".join(violation_sections))
        lines.append("")

    advisory_sections = _detail_sections(PASS)
    if advisory_sections:
        lines.append("## Advisories (non-blocking)")
        lines.append("")
        lines.append("\n\n".join(advisory_sections))
        lines.append("")

    accepted_lines = []
    for repo, std, cell in entries:
        for d in cell.details:
            if d.get("accepted"):
                accepted_lines.append(f"- {repo} / {std} / {d['id']} — {d['exception_reason']}")
    if accepted_lines:
        lines.append("## Accepted exceptions in effect")
        lines.append("")
        lines.extend(accepted_lines)
        lines.append("")

    unknown_lines = []
    for repo, std, cell in entries:
        if cell.status == UNKNOWN:
            unknown_lines.append(f"- {repo} / {std} — {cell.note}")
    if unknown_lines:
        lines.append("## Unknown (work items, not failures)")
        lines.append("")
        lines.extend(unknown_lines)
        lines.append("")

    if unused_exceptions:
        lines.append("## Stale exceptions (matched nothing — delete or fix)")
        lines.append("")
        for entry in unused_exceptions:
            lines.append(f"- {entry['repo']} / {entry['standard']} / {entry['finding']} — {entry['reason']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
