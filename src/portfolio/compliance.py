"""Per-repo compliance cell resolution — shared by `foundation` and `scan`."""
from datetime import date, datetime
from pathlib import Path

from . import checkers, wiring
from .contract import VERSIONED_STANDARDS, Contract, current_standard_versions, parse_contract
from .matrix import (
    CHECKS,
    COLUMNS,
    STANDARDS,
    VIOLATION,
    CheckResult,
    Row,
    na_cell,
    resolve_cell_local,
    unknown_cell,
)

UNDECLARED_NOTE = "standards not declared (pending rollout)"
NO_MANIFEST_NOTE = "no manifest"
UNREADABLE_NOTE = "frontmatter unreadable"

_PER_REPO_CHECKERS = {
    "project": lambda repo: checkers.check_project(repo),
    "security": lambda repo: checkers.check_security(repo),
    "code": lambda repo: checkers.check_code(repo),
}


def _unknown_row(repo: Path, note: str) -> Row:
    return Row(repo=repo.name, path=str(repo),
               cells={col: unknown_cell(note) for col in COLUMNS})


def _with_version_findings(result: CheckResult, std: str, pin,
                           current: dict) -> CheckResult:
    """Inject version-drift/unpinned findings. A pin is an acknowledgment, not a
    behavior selector — drift is known regardless of checker status, so it
    escalates to violation even over an unknown checker result."""
    if std not in VERSIONED_STANDARDS:
        return result                       # infra: unversioned in WS-1.3
    current_version = current.get(std)
    if current_version is None:             # no STANDARD_VERSION file: note, never drift
        note = f"{std} standard version unknown (no STANDARD_VERSION)"
        note = f"{result.note}; {note}" if result.note else note
        return CheckResult(std, result.status, details=result.details, note=note)
    if pin is None:
        detail = {"id": f"{std}.version-unpinned",
                  "message": f"standard version not pinned (current {current_version})"}
    elif pin != current_version:
        detail = {"id": f"{std}.version-drift",
                  "message": f"pinned {pin}, current {current_version}"}
    else:
        return result
    return CheckResult(std, VIOLATION, details=[*result.details, detail],
                       note=result.note)


def _parse_or_unknown(fm: dict | None) -> tuple[Contract | None, str | None]:
    """Classify a repo's frontmatter. Returns (contract, None) when declared,
    or (None, note) for any all-unknown case (no manifest, unreadable, fatal
    contract marker, or undeclared standards)."""
    if fm is None:
        return None, NO_MANIFEST_NOTE
    if "_yaml_error" in fm:
        return None, UNREADABLE_NOTE
    contract = parse_contract(fm)
    if contract.fatal:
        return None, contract.fatal
    if not contract.declared:
        return None, UNDECLARED_NOTE
    return contract, None


def _resolve_declared(repo: Path, fm: dict, contract: Contract, current: dict,
                       today: date) -> tuple[dict, set[int]]:
    """Cells for a declared repo, excluding `infra` (resolved in the batch pass)."""
    cells = {}
    used: set[int] = set()
    for std in STANDARDS:
        if std not in contract.standards:
            cells[std] = na_cell()
            continue
        if std == "infra":
            continue                    # resolved in the batch pass below
        result = _PER_REPO_CHECKERS[std](repo)
        result = _with_version_findings(result, std, contract.standards[std], current)
        cell, u = resolve_cell_local(result, contract.exceptions, today)
        cells[std] = cell
        used |= u

    checks_result = wiring.check_required_checks(
        repo, contract.required_checks, fm.get("foundation") is True)
    cell, u = resolve_cell_local(checks_result, contract.exceptions, today)
    cells[CHECKS] = cell
    used |= u
    return cells, used


def _resolve_infra(rows: list[Row], declared: list[tuple[Path, dict, Contract]],
                   used_by_repo: dict[str, set[int]], now: datetime, today: date) -> None:
    rows_by_name = {row.repo: row for row in rows}
    repo_resources = {
        repo.name: fm.get("coolify_resources") or []
        for repo, fm, contract in declared
        if "infra" in contract.standards
    }
    if not repo_resources:
        return
    infra_results = checkers.check_infra(repo_resources, now)
    contracts = {repo.name: contract for repo, fm, contract in declared}
    for name, result in infra_results.items():
        cell, u = resolve_cell_local(result, contracts[name].exceptions, today)
        rows_by_name[name].cells["infra"] = cell
        used_by_repo[name] |= u


def build_rows(repo_fm_pairs, now: datetime, today: date):
    """Resolve compliance cells for (repo_path, frontmatter|None) pairs.

    Returns (rows in input order, {repo_name: [stale exception entries]}).
    fm None -> all-unknown "no manifest" row. Undeclared/fatal contracts -> all-unknown
    rows without running any checker (bounds scan runtime).
    """
    current = current_standard_versions()
    rows: list[Row] = []
    declared: list[tuple[Path, dict, Contract]] = []
    used_by_repo: dict[str, set[int]] = {}
    stale_by_repo: dict[str, list[dict]] = {}

    for repo, fm in repo_fm_pairs:
        contract, note = _parse_or_unknown(fm)
        if note is not None:
            rows.append(_unknown_row(repo, note))
            continue

        cells, used = _resolve_declared(repo, fm, contract, current, today)
        row = Row(repo=repo.name, path=str(repo), cells=cells)
        rows.append(row)
        declared.append((repo, fm, contract))
        used_by_repo[repo.name] = used

    _resolve_infra(rows, declared, used_by_repo, now, today)

    for repo, _fm, contract in declared:
        stale = [entry for i, entry in enumerate(contract.exceptions)
                 if i not in used_by_repo[repo.name]]
        if stale:
            stale_by_repo[repo.name] = stale
    return rows, stale_by_repo
