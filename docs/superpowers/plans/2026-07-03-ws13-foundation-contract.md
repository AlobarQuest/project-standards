# WS-1.3 foundation_contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the PROJECT.md declaration into the full `foundation_contract` (standard versions + required_checks + exceptions) and widen the conformance matrix from the 8-repo foundational set to the whole portfolio via `portfolio scan`.

**Architecture:** A new `contract.py` parses the frontmatter contract; `wiring.py` statically verifies required_checks executors; `compliance.py` becomes the shared per-repo cell-resolution core consumed by both `portfolio foundation` (behavior unchanged) and `portfolio scan` (gains a compliance section). Exceptions move from the central toml (now machine-scope only) into each repo's frontmatter.

**Tech Stack:** Python 3.12, stdlib + PyYAML (already a dependency). Tests: pytest. Repo: `~/Projects/project-standards`, branch `feat/ws13-foundation-contract`.

**Spec:** `docs/superpowers/specs/2026-07-03-ws13-foundation-contract-design.md` — read it first; its Decisions table and §4 limitation wording are binding.

## Global Constraints

- Python 3.12+; no new dependencies.
- All work in `~/Projects/project-standards` on branch `feat/ws13-foundation-contract`, EXCEPT Task 9 which edits other repos (each on its own branch + PR; NEVER merge — Devon merges).
- Run tests with `make test` (or `uv run pytest tests/ -q`); full gate is `make check`.
- Five cell states only: `pass`, `violation`, `accepted-exception`, `not-applicable`, `unknown`. No sixth state.
- The versioned standards are exactly `project`, `code`, `security` (files); `infra` is unversioned in WS-1.3 (`infra: null` pin is legitimate and produces NO finding).
- `portfolio foundation` exit-code semantics unchanged (1 on violations). `portfolio scan` never blocks.
- Frontmatter YAML parses bare dates (`added: 2026-07-03`) into `datetime.date` objects — every consumer must normalize date-or-string.
- Commit after every task with a conventional message; end commit messages with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_0182VMhMAuBf1i6bRQVkGHWg`.

---

### Task 1: Contract parsing + standard-version resolution (`contract.py`)

**Files:**
- Create: `STANDARD_VERSION` (repo root, content `1.0\n`)
- Create: `src/portfolio/contract.py`
- Modify: `src/portfolio/config.py` (append path helpers)
- Test: `tests/test_contract.py`

**Interfaces:**
- Consumes: `config` path helpers; `exceptions.validate_local` (Task 2 — for Task 1, contract stores RAW exceptions and validation is wired in Task 2's final step; see Step 6).
- Produces: `Contract` dataclass with fields `fatal: str | None`, `declared: bool`, `standards: dict[str, str | None]`, `required_checks: list`, `exceptions: list`, `errors: list[str]`; functions `parse_contract(fm: dict) -> Contract`, `current_standard_versions() -> dict[str, str | None]`; constants `CONTRACT_VERSION = 1`, `VERSIONED_STANDARDS = ("project", "code", "security")`. Config gains `project_standards_repo()`, `standards_repos()`, `claude_settings_path()`, `launchagents_dir()`.

- [ ] **Step 1: Add config path helpers**

Append to `src/portfolio/config.py`:

```python
def project_standards_repo() -> Path:
    override = os.environ.get("PROJECT_STANDARDS_REPO")
    return Path(override) if override else Path(__file__).resolve().parents[2]

def standards_repos() -> dict[str, Path]:
    return {
        "project": project_standards_repo(),
        "code": code_standards_repo(),
        "security": security_standards_repo(),
    }

def claude_settings_path() -> Path:
    override = os.environ.get("CLAUDE_SETTINGS_JSON")
    return Path(override) if override else Path.home() / ".claude" / "settings.json"

def launchagents_dir() -> Path:
    override = os.environ.get("LAUNCHAGENTS_DIR")
    return Path(override) if override else Path.home() / "Library" / "LaunchAgents"
```

- [ ] **Step 2: Create `STANDARD_VERSION`**

```bash
printf '1.0\n' > STANDARD_VERSION
```

- [ ] **Step 3: Write failing tests**

Create `tests/test_contract.py`:

```python
from pathlib import Path

from portfolio.contract import (
    Contract, parse_contract, current_standard_versions, CONTRACT_VERSION,
)


def test_list_form_is_declared_but_unpinned():
    c = parse_contract({"applicable_standards": ["project", "code"]})
    assert c.declared and c.fatal is None
    assert c.standards == {"project": None, "code": None}


def test_map_form_with_pins_and_null():
    c = parse_contract({"applicable_standards": {"project": "1.0", "infra": None}})
    assert c.declared
    assert c.standards == {"project": "1.0", "infra": None}


def test_missing_or_empty_is_undeclared():
    assert parse_contract({}).declared is False
    assert parse_contract({"applicable_standards": []}).declared is False
    assert parse_contract({"applicable_standards": {}}).declared is False


def test_unknown_standard_key_is_error():
    c = parse_contract({"applicable_standards": {"projct": "1.0"}})
    assert not c.declared
    assert any("projct" in e for e in c.errors)


def test_bad_types_are_errors_not_crashes():
    c = parse_contract({"applicable_standards": "project"})
    assert not c.declared and c.errors
    c = parse_contract({"applicable_standards": {"project": 1.0}})
    assert not c.declared and c.errors


def test_future_contract_marker_is_fatal():
    c = parse_contract({"foundation_contract": 2,
                        "applicable_standards": {"project": "1.0"}})
    assert c.fatal is not None
    assert not c.declared


def test_contract_marker_1_is_accepted():
    c = parse_contract({"foundation_contract": 1,
                        "applicable_standards": {"project": "1.0"}})
    assert c.fatal is None and c.declared


def test_required_checks_passthrough():
    entries = [{"id": "quality", "executor": "github-actions:quality.yml"}]
    c = parse_contract({"applicable_standards": {"project": "1.0"},
                        "required_checks": entries})
    assert c.required_checks == entries


def test_required_checks_non_list_is_error():
    c = parse_contract({"applicable_standards": {"project": "1.0"},
                        "required_checks": "quality"})
    assert c.required_checks == [] and c.errors


def test_current_versions_reads_files(monkeypatch, tmp_path):
    for std in ("project", "code", "security"):
        repo = tmp_path / std
        repo.mkdir()
    (tmp_path / "project" / "STANDARD_VERSION").write_text("1.0\n")
    (tmp_path / "code" / "STANDARD_VERSION").write_text("2.1\n")
    # security: no file -> None
    monkeypatch.setenv("PROJECT_STANDARDS_REPO", str(tmp_path / "project"))
    monkeypatch.setenv("CODE_STANDARDS_REPO", str(tmp_path / "code"))
    monkeypatch.setenv("SECURITY_STANDARDS_REPO", str(tmp_path / "security"))
    assert current_standard_versions() == {"project": "1.0", "code": "2.1",
                                           "security": None}
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/test_contract.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'portfolio.contract'`

- [ ] **Step 5: Implement `src/portfolio/contract.py`**

```python
"""Parse the foundation_contract block from PROJECT.md frontmatter."""
from dataclasses import dataclass, field

from . import config
from .schema import KNOWN_STANDARDS

CONTRACT_VERSION = 1
VERSIONED_STANDARDS = ("project", "code", "security")


@dataclass
class Contract:
    fatal: str | None = None      # unrecognized schema marker — treat all cells unknown
    declared: bool = False        # applicable_standards present, valid, non-empty
    standards: dict = field(default_factory=dict)       # std -> pin (str | None)
    required_checks: list = field(default_factory=list)  # raw entries; wiring validates
    exceptions: list = field(default_factory=list)       # validated entries (Task 2)
    errors: list = field(default_factory=list)           # shape problems (never mask)


def parse_contract(fm: dict) -> Contract:
    c = Contract()
    marker = fm.get("foundation_contract")
    if marker is not None and marker != CONTRACT_VERSION:
        c.fatal = f"foundation_contract must be {CONTRACT_VERSION}, got {marker!r}"
        return c

    raw = fm.get("applicable_standards")
    if isinstance(raw, list):
        if raw and all(isinstance(s, str) for s in raw):
            c.standards = {s: None for s in raw}
        elif raw:
            c.errors.append(f"applicable_standards list items must be strings: {raw!r}")
    elif isinstance(raw, dict):
        bad = {k: v for k, v in raw.items()
               if not isinstance(k, str) or not (v is None or isinstance(v, str))}
        if bad:
            c.errors.append(f"applicable_standards pins must be str or null: {bad!r}")
        elif raw:
            c.standards = dict(raw)
    elif raw is not None:
        c.errors.append(f"applicable_standards must be a list or mapping, got {raw!r}")

    unknown = [k for k in c.standards if k not in KNOWN_STANDARDS]
    if unknown:
        c.errors.append(f"unknown standards in applicable_standards: {unknown!r}")
        c.standards = {}
    c.declared = bool(c.standards)

    checks = fm.get("required_checks")
    if isinstance(checks, list):
        c.required_checks = checks
    elif checks is not None:
        c.errors.append(f"required_checks must be a list, got {checks!r}")

    c.exceptions = fm.get("exceptions") or []
    if not isinstance(c.exceptions, list):
        c.errors.append(f"exceptions must be a list, got {c.exceptions!r}")
        c.exceptions = []
    return c


def current_standard_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for std, repo in config.standards_repos().items():
        try:
            text = (repo / "STANDARD_VERSION").read_text().strip()
        except OSError:
            out[std] = None
            continue
        out[std] = text or None
    return out
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_contract.py -q`
Expected: all PASS. (Exception-entry validation is intentionally not here — Task 2 adds `exceptions.validate_local` and re-wires `parse_contract` to call it; the raw passthrough above is the Task-1 state.)

- [ ] **Step 7: Run the full suite, then commit**

Run: `uv run pytest tests/ -q` — expected: no regressions.

```bash
git add STANDARD_VERSION src/portfolio/contract.py src/portfolio/config.py tests/test_contract.py
git commit -m "feat: foundation_contract parsing + STANDARD_VERSION resolution"
```

---

### Task 2: Frontmatter exception entries (`exceptions.py`)

**Files:**
- Modify: `src/portfolio/exceptions.py`
- Modify: `src/portfolio/contract.py` (wire validation in)
- Test: `tests/test_exceptions.py` (append), `tests/test_contract.py` (append)

**Interfaces:**
- Consumes: `Contract` from Task 1.
- Produces: `validate_local(entries) -> tuple[list[dict], list[str]]` (valid entries with dates normalized to ISO strings, error strings); `local_matches(entry, standard, finding_id) -> bool`; `expired(entry, today: date) -> bool`; constant `LOCAL_STANDARDS = {"project", "security", "code", "infra", "checks"}`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_exceptions.py`:

```python
from datetime import date

from portfolio.exceptions import validate_local, local_matches, expired


def _entry(**over):
    base = {"standard": "code", "finding": "code.not-onboarded",
            "reason": "r", "added": "2026-07-03"}
    return {**base, **over}


def test_validate_local_accepts_and_normalizes_dates():
    valid, errors = validate_local([_entry(added=date(2026, 7, 3),
                                           review_by=date(2026, 9, 1))])
    assert errors == []
    assert valid[0]["added"] == "2026-07-03"
    assert valid[0]["review_by"] == "2026-09-01"


def test_validate_local_rejects_missing_fields_and_bad_standard():
    valid, errors = validate_local([
        {"standard": "code"},                 # missing finding/reason/added
        _entry(standard="nope"),
        "not-a-mapping",
    ])
    assert valid == [] and len(errors) == 3


def test_validate_local_rejects_unparseable_review_by():
    valid, errors = validate_local([_entry(review_by="soonish")])
    assert valid == [] and errors


def test_local_matches_uses_fnmatch_and_standard():
    e = _entry(finding="code.*")
    assert local_matches(e, "code", "code.not-onboarded")
    assert not local_matches(e, "security", "code.not-onboarded")


def test_expired():
    assert not expired(_entry(), date(2026, 7, 3))                      # no review_by
    assert not expired(_entry(review_by="2026-09-01"), date(2026, 9, 1))  # boundary: not yet
    assert expired(_entry(review_by="2026-09-01"), date(2026, 9, 2))
```

Append to `tests/test_contract.py`:

```python
def test_contract_validates_exceptions_and_drops_invalid():
    fm = {"applicable_standards": {"code": "1.0"},
          "exceptions": [
              {"standard": "code", "finding": "code.*", "reason": "r",
               "added": "2026-07-03"},
              {"standard": "code"},          # invalid -> dropped + error
          ]}
    c = parse_contract(fm)
    assert len(c.exceptions) == 1
    assert c.errors
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_exceptions.py tests/test_contract.py -q`
Expected: FAIL — `ImportError: cannot import name 'validate_local'`

- [ ] **Step 3: Implement in `src/portfolio/exceptions.py`**

Append (keep the existing central-file `load`/`matches` untouched — machine scope still uses them):

```python
from datetime import date

LOCAL_REQUIRED = ("standard", "finding", "reason", "added")
LOCAL_STANDARDS = {"project", "security", "code", "infra", "checks"}


def _norm_date(value):
    """YAML parses bare dates to datetime.date; accept date or ISO string."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            date.fromisoformat(value)
        except ValueError:
            return None
        return value
    return None


def validate_local(entries) -> tuple[list[dict], list[str]]:
    """Validate PROJECT.md frontmatter exception entries.

    Returns (valid entries with dates normalized to ISO strings, errors).
    An invalid entry is dropped — it must never mask a finding.
    """
    valid, errors = [], []
    for i, raw in enumerate(entries):
        if not isinstance(raw, dict):
            errors.append(f"exceptions[{i}] must be a mapping, got {type(raw).__name__}")
            continue
        entry = dict(raw)
        problems = []
        for f in ("standard", "finding", "reason"):
            if not isinstance(entry.get(f), str) or not entry[f]:
                problems.append(f"missing non-empty field {f!r}")
        if entry.get("standard") not in LOCAL_STANDARDS:
            problems.append(f"standard must be one of {sorted(LOCAL_STANDARDS)}")
        added = _norm_date(entry.get("added"))
        if added is None:
            problems.append("added must be an ISO date")
        entry["added"] = added
        if "review_by" in entry:
            review_by = _norm_date(entry["review_by"])
            if review_by is None:
                problems.append("review_by must be an ISO date")
            entry["review_by"] = review_by
        if problems:
            errors.append(f"exceptions[{i}]: " + "; ".join(problems))
            continue
        valid.append(entry)
    return valid, errors


def local_matches(entry: dict, standard: str, finding_id: str) -> bool:
    return (entry["standard"] == standard
            and fnmatch.fnmatch(finding_id, entry["finding"]))


def expired(entry: dict, today: date) -> bool:
    review_by = entry.get("review_by")
    return bool(review_by) and date.fromisoformat(review_by) < today
```

- [ ] **Step 4: Wire validation into `parse_contract`**

In `src/portfolio/contract.py`, add `from . import exceptions` and replace the exceptions block at the end of `parse_contract`:

```python
    raw_exc = fm.get("exceptions")
    if raw_exc is None:
        raw_exc = []
    elif not isinstance(raw_exc, list):
        # isinstance BEFORE any falsy coercion: `exceptions: {}` or `0` must
        # record an error, never silently read as "no exceptions" (T1 review).
        c.errors.append(f"exceptions must be a list, got {raw_exc!r}")
        raw_exc = []
    c.exceptions, exc_errors = exceptions.validate_local(raw_exc)
    c.errors.extend(exc_errors)
    return c
```

Also in this task: remove the dead imports in `tests/test_contract.py` (`Path`, `Contract`, `CONTRACT_VERSION` are unused — T1 review Minor), and add a test that a falsy non-list `exceptions` value records an error:

```python
def test_exceptions_falsy_non_list_is_error():
    c = parse_contract({"applicable_standards": {"project": "1.0"},
                        "exceptions": {}})
    assert c.exceptions == [] and c.errors
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_exceptions.py tests/test_contract.py -q` — expected: all PASS.

- [ ] **Step 6: Full suite + commit**

Run: `uv run pytest tests/ -q` — no regressions.

```bash
git add src/portfolio/exceptions.py src/portfolio/contract.py tests/test_exceptions.py tests/test_contract.py
git commit -m "feat: frontmatter exception entries with review_by expiry"
```

---

### Task 3: Matrix checks column + local cell resolution (`matrix.py`)

**Files:**
- Modify: `src/portfolio/matrix.py`
- Test: `tests/test_matrix.py` (append)

**Interfaces:**
- Consumes: `exceptions.local_matches`, `exceptions.expired` (Task 2).
- Produces: constants `CHECKS = "checks"`, `COLUMNS = STANDARDS + [CHECKS]`; `unknown_cell(note) -> Cell`; `resolve_cell_local(result: CheckResult, entries: list[dict], today: date) -> tuple[Cell, set[int]]`. `build_report`/`render_digest` iterate `COLUMNS` (report key `"standards"` now lists 5 columns).

- [ ] **Step 1: Write failing tests**

Append to `tests/test_matrix.py`:

```python
from datetime import date

from portfolio.matrix import (
    CHECKS, COLUMNS, CheckResult, NA, UNKNOWN, VIOLATION, ACCEPTED,
    resolve_cell_local, unknown_cell,
)


def _exc(**over):
    base = {"standard": "code", "finding": "code.*", "reason": "accepted",
            "added": "2026-07-03"}
    return {**base, **over}

TODAY = date(2026, 7, 3)


def test_columns_include_checks():
    assert COLUMNS == ["project", "security", "code", "infra", "checks"]


def test_unknown_cell_carries_note():
    cell = unknown_cell("no manifest")
    assert cell.status == UNKNOWN and cell.note == "no manifest"


def test_resolve_local_pass_unknown_na_pass_through():
    for status in ("pass", UNKNOWN, NA):
        cell, used = resolve_cell_local(CheckResult("code", status), [], TODAY)
        assert cell.status == status and used == set()


def test_resolve_local_masks_matching_violation():
    result = CheckResult("code", VIOLATION,
                         details=[{"id": "code.not-onboarded", "message": "m"}])
    cell, used = resolve_cell_local(result, [_exc()], TODAY)
    assert cell.status == ACCEPTED and used == {0}
    assert cell.details[0]["exception_reason"] == "accepted"


def test_resolve_local_expired_exception_does_not_mask():
    result = CheckResult("code", VIOLATION,
                         details=[{"id": "code.not-onboarded", "message": "m"}])
    cell, used = resolve_cell_local(result, [_exc(review_by="2026-06-01")], TODAY)
    assert cell.status == VIOLATION
    assert cell.details[0]["exception_expired"] == "2026-06-01"
    assert used == {0}          # matched (so not stale), just expired


def test_resolve_local_wrong_standard_does_not_mask():
    result = CheckResult("security", VIOLATION,
                         details=[{"id": "security.x", "message": "m"}])
    cell, used = resolve_cell_local(result, [_exc()], TODAY)
    assert cell.status == VIOLATION and used == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_matrix.py -q`
Expected: FAIL — `ImportError: cannot import name 'CHECKS'`

- [ ] **Step 3: Implement in `src/portfolio/matrix.py`**

Add after the `STANDARDS` line:

```python
CHECKS = "checks"                                       # required_checks wiring column
COLUMNS = STANDARDS + [CHECKS]                          # full column order
```

Update the `CheckResult.status` comment to `# pass | violation | unknown | not-applicable`.

Add after `na_cell`:

```python
def unknown_cell(note: str) -> Cell:
    return Cell(UNKNOWN, [], note)


def resolve_cell_local(result: CheckResult, entries: list[dict], today) -> tuple[Cell, set[int]]:
    """resolve_cell against a repo's own frontmatter exceptions (no repo field,
    review_by expiry). Matched-but-expired entries count as used (not stale) but
    do not mask."""
    if result.status in (PASS, UNKNOWN, NA):
        return Cell(result.status, result.details, result.note), set()

    used: set[int] = set()
    details = []
    for detail in result.details:
        detail = dict(detail)
        detail_id = detail.get("id")
        if not isinstance(detail_id, str):
            detail_id = ""
        matched = [i for i, e in enumerate(entries)
                   if exceptions.local_matches(e, result.standard, detail_id)]
        active = [i for i in matched if not exceptions.expired(entries[i], today)]
        if active:
            detail["accepted"] = True
            detail["exception_reason"] = entries[active[0]]["reason"]
        elif matched:
            detail["exception_expired"] = entries[matched[0]].get("review_by")
        used.update(matched)
        details.append(detail)

    if details and all(d.get("accepted") for d in details):
        status = ACCEPTED
    else:
        status = VIOLATION
    return Cell(status, details, result.note), used
```

Then replace every rendering/report iteration over `STANDARDS` with `COLUMNS`:
- `build_report`: `"standards": COLUMNS` and `for std in COLUMNS` in the cells dict.
- `render_digest`: header/sep loops and the row-cells join over `COLUMNS`; the `entries` comprehension over `COLUMNS`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_matrix.py -q` — all PASS.

- [ ] **Step 5: Full suite + commit**

Run: `uv run pytest tests/ -q`. `test_foundation.py` may still pass (rows without a `checks` cell render as `—` via the `na_cell()` fallback in `render_digest`/`build_report`). If a test asserts on the exact `"standards"` list, update it to expect 5 columns.

```bash
git add src/portfolio/matrix.py tests/test_matrix.py
git commit -m "feat: checks column + frontmatter-exception cell resolution"
```

---

### Task 4: Static wiring verification (`wiring.py`)

**Files:**
- Create: `src/portfolio/wiring.py`
- Test: `tests/test_wiring.py`

**Interfaces:**
- Consumes: `config.claude_settings_path()`, `config.launchagents_dir()` (Task 1); `CheckResult`, `PASS`, `VIOLATION`, `NA` from matrix.
- Produces: `check_required_checks(repo: Path, entries: list, foundation: bool) -> CheckResult` with `standard="checks"`. Finding ids: `checks.none-declared`, `checks.bad-executor`, `checks.not-wired`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_wiring.py`:

```python
import json

import pytest

from portfolio.wiring import check_required_checks


@pytest.fixture
def machine(monkeypatch, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"Stop": [{"matcher": ".*", "hooks": [
        {"type": "command", "command": "/Users/devon/.claude/hooks/bws-scan-gate.sh"}
    ]}]}}))
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    (agents / "com.devon.security-scan.plist").write_text("<plist/>")
    monkeypatch.setenv("CLAUDE_SETTINGS_JSON", str(settings))
    monkeypatch.setenv("LAUNCHAGENTS_DIR", str(agents))


def _repo(tmp_path, workflow="quality.yml", body="jobs:\n  quality:\n    steps: []\n"):
    repo = tmp_path / "r"
    wf = repo / ".github" / "workflows" / workflow
    wf.parent.mkdir(parents=True)
    wf.write_text(body)
    return repo


def _ids(result):
    return [d["id"] for d in result.details]


def test_none_declared_foundation_vs_not(tmp_path, machine):
    repo = tmp_path / "empty"; repo.mkdir()
    assert _ids(check_required_checks(repo, [], foundation=True)) == ["checks.none-declared"]
    assert check_required_checks(repo, [], foundation=False).status == "not-applicable"


def test_workflow_wired_and_missing(tmp_path, machine):
    repo = _repo(tmp_path)
    ok = check_required_checks(
        repo, [{"id": "quality", "executor": "github-actions:quality.yml"}], True)
    assert ok.status == "pass"
    missing = check_required_checks(
        repo, [{"id": "x", "executor": "github-actions:nope.yml"}], True)
    assert _ids(missing) == ["checks.not-wired"]


def test_workflow_job_key_checked(tmp_path, machine):
    repo = _repo(tmp_path)
    ok = check_required_checks(
        repo, [{"id": "q", "executor": "github-actions:quality.yml:quality"}], True)
    assert ok.status == "pass"
    bad = check_required_checks(
        repo, [{"id": "q", "executor": "github-actions:quality.yml:missing"}], True)
    assert _ids(bad) == ["checks.not-wired"]


def test_hook_checks_settings_registration(tmp_path, machine):
    repo = tmp_path / "r2"; repo.mkdir()
    ok = check_required_checks(repo, [{"id": "gate", "executor": "hook:bws-scan-gate.sh"}], True)
    assert ok.status == "pass"
    bad = check_required_checks(repo, [{"id": "g", "executor": "hook:unregistered.sh"}], True)
    assert _ids(bad) == ["checks.not-wired"]


def test_launchagent_plist_existence(tmp_path, machine):
    repo = tmp_path / "r3"; repo.mkdir()
    ok = check_required_checks(
        repo, [{"id": "scan", "executor": "launchagent:com.devon.security-scan"}], True)
    assert ok.status == "pass"
    bad = check_required_checks(
        repo, [{"id": "s", "executor": "launchagent:com.devon.nope"}], True)
    assert _ids(bad) == ["checks.not-wired"]


def test_bad_executor_and_malformed_entry(tmp_path, machine):
    repo = tmp_path / "r4"; repo.mkdir()
    result = check_required_checks(repo, [
        {"id": "a", "executor": "carrier-pigeon:coop"},
        {"executor": "github-actions:quality.yml"},        # missing id
        "quality",                                          # not a mapping
    ], True)
    assert _ids(result) == ["checks.bad-executor"] * 3
    assert result.status == "violation"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_wiring.py -q`
Expected: FAIL — no module `portfolio.wiring`.

- [ ] **Step 3: Implement `src/portfolio/wiring.py`**

```python
"""Static wiring verification for required_checks.

Verifies a declared check is INVOKED somewhere (workflow file + job, hook
registered in settings.json, LaunchAgent plist present). It does NOT prove the
check does real work — "wired but runs hollow" (the quality.yml incident) needs
execution evidence, a future drift-loop enhancement. See spec §4.
"""
import json
from pathlib import Path

import yaml

from . import config
from .matrix import CheckResult, NA, PASS, VIOLATION


def check_required_checks(repo: Path, entries: list, foundation: bool) -> CheckResult:
    if not entries:
        if foundation:
            details = [{"id": "checks.none-declared",
                        "message": "foundation repo declares no required_checks"}]
            return CheckResult("checks", VIOLATION, details=details)
        return CheckResult("checks", NA)

    details = [d for d in (_verify_entry(repo, e) for e in entries) if d]
    return CheckResult("checks", VIOLATION if details else PASS, details=details)


def _verify_entry(repo: Path, entry) -> dict | None:
    if (not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
            or not isinstance(entry.get("executor"), str)):
        return {"id": "checks.bad-executor",
                "message": f"malformed required_checks entry: {entry!r}"}
    check_id, executor = entry["id"], entry["executor"]
    kind, _, rest = executor.partition(":")
    if kind == "github-actions" and rest:
        return _verify_workflow(repo, check_id, rest)
    if kind == "hook" and rest:
        return _verify_hook(check_id, rest)
    if kind == "launchagent" and rest:
        return _verify_launchagent(check_id, rest)
    return {"id": "checks.bad-executor",
            "message": f"{check_id}: unparseable executor {executor!r}"}


def _verify_workflow(repo: Path, check_id: str, rest: str) -> dict | None:
    filename, _, job = rest.partition(":")
    path = repo / ".github" / "workflows" / filename
    if not path.is_file():
        return {"id": "checks.not-wired",
                "message": f"{check_id}: workflow {filename} not found"}
    if job:
        try:
            data = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError):
            return {"id": "checks.not-wired",
                    "message": f"{check_id}: workflow {filename} unreadable"}
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not isinstance(jobs, dict) or job not in jobs:
            return {"id": "checks.not-wired",
                    "message": f"{check_id}: job {job!r} not in {filename}"}
    return None


def _verify_hook(check_id: str, name: str) -> dict | None:
    # A hook only runs if REGISTERED in settings.json — file existence in
    # ~/.claude/hooks/ proves deployment, not wiring (deployed != wired).
    path = config.claude_settings_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"id": "checks.not-wired",
                "message": f"{check_id}: cannot read hook registrations in {path}"}
    if name not in json.dumps(data.get("hooks", {})):
        return {"id": "checks.not-wired",
                "message": f"{check_id}: hook {name!r} not registered in settings.json"}
    return None


def _verify_launchagent(check_id: str, label: str) -> dict | None:
    # Limitation (spec §4): plist existence != loaded; launchctl state is
    # runtime-flaky, so file presence is the accepted static proxy.
    plist = config.launchagents_dir() / f"{label}.plist"
    if not plist.is_file():
        return {"id": "checks.not-wired",
                "message": f"{check_id}: LaunchAgent {label}.plist not found"}
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_wiring.py -q` — all PASS.

- [ ] **Step 5: Full suite + commit**

```bash
git add src/portfolio/wiring.py tests/test_wiring.py
git commit -m "feat: static wiring verification for required_checks"
```

---

### Task 5: Schema validation of the contract block (`schema.py`)

**Files:**
- Modify: `src/portfolio/schema.py`
- Test: `tests/test_schema.py` (append)

**Interfaces:**
- Consumes: `contract.parse_contract` (Tasks 1–2). NOTE: `contract.py` imports `KNOWN_STANDARDS` from `schema.py`; do NOT import `contract` at module top in `schema.py` — import inside `validate_frontmatter` to avoid the cycle.
- Produces: `validate_frontmatter` accepts map-form `applicable_standards`; emits `FAIL contract_error` findings for `Contract.fatal`/`Contract.errors`. Existing list-form behavior and all other findings unchanged.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_schema.py` (mirror the existing test style — call `validate_frontmatter` with a base valid fm; look at how existing tests build one and reuse it):

```python
def _codes(findings):
    return [f.code for f in findings]


def test_map_form_applicable_standards_is_valid(base_fm):
    fm = {**base_fm, "applicable_standards": {"project": "1.0", "infra": None}}
    assert "bad_type" not in _codes(validate_frontmatter(fm))
    assert "contract_error" not in _codes(validate_frontmatter(fm))


def test_future_contract_marker_fails(base_fm):
    fm = {**base_fm, "foundation_contract": 2,
          "applicable_standards": {"project": "1.0"}}
    assert "contract_error" in _codes(validate_frontmatter(fm))


def test_malformed_exception_entry_fails(base_fm):
    fm = {**base_fm, "applicable_standards": {"project": "1.0"},
          "exceptions": [{"standard": "project"}]}
    assert "contract_error" in _codes(validate_frontmatter(fm))


def test_bad_required_checks_fails(base_fm):
    fm = {**base_fm, "applicable_standards": {"project": "1.0"},
          "required_checks": "quality"}
    assert "contract_error" in _codes(validate_frontmatter(fm))
```

If `tests/test_schema.py` has no `base_fm` fixture, add one matching the REQUIRED_ACTIVE fields:

```python
@pytest.fixture
def base_fm():
    return {"name": "x", "tier": "active", "status": "active", "version": "1.0",
            "version_source": "pyproject", "purpose": "p", "updated": "2026-07-03"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_schema.py -q`
Expected: new tests FAIL (map form currently emits `bad_type`; no `contract_error` code exists).

- [ ] **Step 3: Implement**

In `schema.py`, replace the `applicable_standards` block of `validate_frontmatter` (the `if "applicable_standards" in fm:` branch) with contract-based validation:

```python
    from .contract import parse_contract   # local import: contract imports KNOWN_STANDARDS

    contract = parse_contract(fm)
    if contract.fatal:
        findings.append(Finding("FAIL", "contract_error", contract.fatal))
    for error in contract.errors:
        findings.append(Finding("FAIL", "contract_error", error))
    applicable_standards_valid = contract.declared
```

Keep the `foundation` bool check and the `coolify_resources` check as they are. Update the `foundation_incomplete` block to use the contract:

```python
    if fm.get("foundation") is True:
        if not contract.declared:
            findings.append(Finding("WARN", "foundation_incomplete",
                                     "foundation is true but applicable_standards is missing or empty"))
        elif "infra" in contract.standards and not fm.get("coolify_resources"):
            findings.append(Finding("WARN", "foundation_incomplete",
                                     "applicable_standards includes infra but coolify_resources is missing or empty"))
```

Delete the now-unused list-only validation lines (the `isinstance(applicable_standards, list)` branch and the `KNOWN_STANDARDS` per-item loop) — `parse_contract` covers both forms; `KNOWN_STANDARDS` stays defined here (contract imports it).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_schema.py tests/test_validator.py -q` — all PASS (validator lint flows through this function; if a validator test asserted the old `bad_enum` message for unknown standards, update it to expect `contract_error`).

- [ ] **Step 5: Full suite + commit**

```bash
git add src/portfolio/schema.py tests/test_schema.py
git commit -m "feat: validate foundation_contract blocks in schema lint"
```

---

### Task 6: Shared compliance core (`compliance.py`)

**Files:**
- Create: `src/portfolio/compliance.py`
- Modify: `tests/conftest.py` (add `standards_env` fixture)
- Test: `tests/test_compliance.py`

**Interfaces:**
- Consumes: `contract.parse_contract`/`current_standard_versions`/`VERSIONED_STANDARDS`, `wiring.check_required_checks`, `checkers.check_project/check_security/check_code/check_infra`, `matrix.resolve_cell_local/unknown_cell/na_cell/Row/CheckResult/COLUMNS/CHECKS/STANDARDS/VIOLATION/UNKNOWN`.
- Produces:
  - `UNDECLARED_NOTE = "standards not declared (pending rollout)"`, `NO_MANIFEST_NOTE = "no manifest"`.
  - `build_rows(repo_fm_pairs, now, today) -> tuple[list[Row], dict[str, list[dict]]]` where `repo_fm_pairs` is `[(Path, dict | None)]` (`None` fm = no/unreadable manifest → all-unknown row; undeclared fm → all-unknown row, NO checkers run; declared fm → checker cells + version findings + checks column + frontmatter-exception resolution). Second return: `{repo_name: [stale exception entries]}`.
  - Rows keep input order; cells keyed by `COLUMNS`.

- [ ] **Step 1: Add the `standards_env` conftest fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def standards_env(monkeypatch, tmp_path):
    """Fake standards repos with STANDARD_VERSION files, so tests never read
    the real ~/Projects checkouts. Returns the dict of repo paths."""
    repos = {}
    for std, env in (("project", "PROJECT_STANDARDS_REPO"),
                     ("code", "CODE_STANDARDS_REPO"),
                     ("security", "SECURITY_STANDARDS_REPO")):
        repo = tmp_path / f".std-{std}"
        repo.mkdir()
        (repo / "STANDARD_VERSION").write_text("1.0\n")
        monkeypatch.setenv(env, str(repo))
        repos[std] = repo
    return repos
```

(Leading dot keeps them out of `_iter_repos` scans when `tmp_path` doubles as a root — same trick as `portfolio_env`.)

- [ ] **Step 2: Write failing tests**

Create `tests/test_compliance.py`:

```python
from datetime import date, datetime
from pathlib import Path

import pytest

from portfolio import compliance
from portfolio.matrix import CheckResult, PASS, VIOLATION, ACCEPTED, UNKNOWN, NA

NOW = datetime(2026, 7, 3, 12, 0, 0)
TODAY = date(2026, 7, 3)


@pytest.fixture
def quiet_checkers(monkeypatch):
    """All real checkers pass; no subprocesses. Records which repos ran."""
    ran = []
    def _mk(std):
        def check(repo):
            ran.append((std, Path(repo).name))
            return CheckResult(std, PASS)
        return check
    monkeypatch.setattr(compliance.checkers, "check_project", _mk("project"))
    monkeypatch.setattr(compliance.checkers, "check_security", _mk("security"))
    monkeypatch.setattr(compliance.checkers, "check_code", _mk("code"))
    monkeypatch.setattr(compliance.checkers, "check_infra",
                        lambda resources, now: {name: CheckResult("infra", PASS)
                                                for name in resources})
    return ran


def _fm(**over):
    base = {"applicable_standards": {"project": "1.0"}}
    return {**base, **over}


def test_no_manifest_row_is_all_unknown(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "bare"; repo.mkdir()
    rows, stale = compliance.build_rows([(repo, None)], NOW, TODAY)
    assert all(c.status == UNKNOWN and c.note == compliance.NO_MANIFEST_NOTE
               for c in rows[0].cells.values())
    assert quiet_checkers == []          # no checkers ran


def test_yaml_error_row_is_all_unknown(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "broken"; repo.mkdir()
    rows, _ = compliance.build_rows([(repo, {"_yaml_error": "boom"})], NOW, TODAY)
    assert all(c.status == UNKNOWN and c.note == compliance.UNREADABLE_NOTE
               for c in rows[0].cells.values())
    assert quiet_checkers == []


def test_undeclared_row_is_all_unknown_without_checkers(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "plain"; repo.mkdir()
    rows, _ = compliance.build_rows([(repo, {"name": "plain"})], NOW, TODAY)
    assert all(c.status == UNKNOWN and c.note == compliance.UNDECLARED_NOTE
               for c in rows[0].cells.values())
    assert quiet_checkers == []


def test_declared_pinned_current_is_green(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "good"; repo.mkdir()
    fm = _fm(required_checks=[], foundation=False)
    rows, _ = compliance.build_rows([(repo, fm)], NOW, TODAY)
    cells = rows[0].cells
    assert cells["project"].status == PASS
    assert cells["security"].status == "not-applicable"
    assert cells["checks"].status == NA                  # non-foundation, none declared


def test_version_drift_is_violation(standards_env, quiet_checkers, tmp_path):
    (standards_env["project"] / "STANDARD_VERSION").write_text("1.1\n")
    repo = tmp_path / "drifty"; repo.mkdir()
    rows, _ = compliance.build_rows([(repo, _fm())], NOW, TODAY)
    cell = rows[0].cells["project"]
    assert cell.status == VIOLATION
    assert any(d["id"] == "project.version-drift" and "1.0" in d["message"]
               and "1.1" in d["message"] for d in cell.details)


def test_unpinned_is_violation_when_current_known(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "listform"; repo.mkdir()
    rows, _ = compliance.build_rows(
        [(repo, {"applicable_standards": ["project"]})], NOW, TODAY)
    cell = rows[0].cells["project"]
    assert cell.status == VIOLATION
    assert any(d["id"] == "project.version-unpinned" for d in cell.details)


def test_missing_standard_version_file_notes_not_drifts(standards_env, quiet_checkers, tmp_path):
    (standards_env["project"] / "STANDARD_VERSION").unlink()
    repo = tmp_path / "nofile"; repo.mkdir()
    rows, _ = compliance.build_rows([(repo, _fm())], NOW, TODAY)
    cell = rows[0].cells["project"]
    assert cell.status == PASS
    assert "version unknown" in (cell.note or "")


def test_infra_null_pin_is_not_a_finding(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "infra"; repo.mkdir()
    fm = {"applicable_standards": {"infra": None}, "coolify_resources": ["u1"]}
    rows, _ = compliance.build_rows([(repo, fm)], NOW, TODAY)
    assert rows[0].cells["infra"].status == PASS


def test_exception_masks_and_stale_reported(standards_env, quiet_checkers, monkeypatch, tmp_path):
    monkeypatch.setattr(compliance.checkers, "check_code", lambda repo: CheckResult(
        "code", VIOLATION, details=[{"id": "code.not-onboarded", "message": "m"}]))
    repo = tmp_path / "excused"; repo.mkdir()
    fm = {"applicable_standards": {"code": "1.0"},
          "exceptions": [
              {"standard": "code", "finding": "code.not-onboarded",
               "reason": "wave 2", "added": "2026-07-03"},
              {"standard": "security", "finding": "security.*",
               "reason": "stale", "added": "2026-07-03"},
          ]}
    rows, stale = compliance.build_rows([(repo, fm)], NOW, TODAY)
    assert rows[0].cells["code"].status == ACCEPTED
    assert [e["reason"] for e in stale["excused"]] == ["stale"]


def test_fatal_contract_marker_all_unknown(standards_env, quiet_checkers, tmp_path):
    repo = tmp_path / "future"; repo.mkdir()
    rows, _ = compliance.build_rows(
        [(repo, {"foundation_contract": 9, "applicable_standards": {"project": "1.0"}})],
        NOW, TODAY)
    assert all(c.status == UNKNOWN for c in rows[0].cells.values())
    assert quiet_checkers == []


def test_foundation_checks_column_wired(standards_env, quiet_checkers, tmp_path, monkeypatch):
    repo = tmp_path / "found"; repo.mkdir()
    wf = repo / ".github" / "workflows" / "quality.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("jobs:\n  quality: {}\n")
    fm = _fm(foundation=True,
             required_checks=[{"id": "quality", "executor": "github-actions:quality.yml"}])
    rows, _ = compliance.build_rows([(repo, fm)], NOW, TODAY)
    assert rows[0].cells["checks"].status == PASS
    fm_none = _fm(foundation=True)
    rows, _ = compliance.build_rows([(repo, fm_none)], NOW, TODAY)
    assert any(d["id"] == "checks.none-declared"
               for d in rows[0].cells["checks"].details)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_compliance.py -q`
Expected: FAIL — no module `portfolio.compliance`.

- [ ] **Step 4: Implement `src/portfolio/compliance.py`**

```python
"""Per-repo compliance cell resolution — shared by `foundation` and `scan`."""
from datetime import date, datetime
from pathlib import Path

from . import checkers, wiring
from .contract import Contract, VERSIONED_STANDARDS, current_standard_versions, parse_contract
from .matrix import (
    CHECKS, COLUMNS, STANDARDS, VIOLATION,
    CheckResult, Row, na_cell, resolve_cell_local, unknown_cell,
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
        if fm is None:
            rows.append(_unknown_row(repo, NO_MANIFEST_NOTE))
            continue
        if "_yaml_error" in fm:
            rows.append(_unknown_row(repo, UNREADABLE_NOTE))
            continue
        contract = parse_contract(fm)
        if contract.fatal:
            rows.append(_unknown_row(repo, contract.fatal))
            continue
        if not contract.declared:
            rows.append(_unknown_row(repo, UNDECLARED_NOTE))
            continue

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

        row = Row(repo=repo.name, path=str(repo), cells=cells)
        rows.append(row)
        declared.append((repo, fm, contract))
        used_by_repo[repo.name] = used

    rows_by_name = {row.repo: row for row in rows}
    repo_resources = {
        repo.name: fm.get("coolify_resources") or []
        for repo, fm, contract in declared
        if "infra" in contract.standards
    }
    if repo_resources:
        infra_results = checkers.check_infra(repo_resources, now)
        contracts = {repo.name: contract for repo, fm, contract in declared}
        for name, result in infra_results.items():
            cell, u = resolve_cell_local(result, contracts[name].exceptions, today)
            rows_by_name[name].cells["infra"] = cell
            used_by_repo[name] |= u

    for repo, fm, contract in declared:
        stale = [entry for i, entry in enumerate(contract.exceptions)
                 if i not in used_by_repo[repo.name]]
        if stale:
            stale_by_repo[repo.name] = stale
    return rows, stale_by_repo
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_compliance.py -q` — all PASS.

- [ ] **Step 6: Full suite + commit**

```bash
git add src/portfolio/compliance.py tests/test_compliance.py tests/conftest.py
git commit -m "feat: shared compliance core (contract cells, version findings, checks column)"
```

---

### Task 7: Refactor `foundation` onto the compliance core

**Files:**
- Modify: `src/portfolio/foundation.py`
- Modify: `src/portfolio/matrix.py` (digest: stale-exception + expired rendering)
- Modify: `foundation-exceptions.toml` (header: machine scope only)
- Test: `tests/test_foundation.py` (update fixtures + add drift e2e)

**Interfaces:**
- Consumes: `compliance.build_rows` (Task 6); central `exceptions.load`/`resolve_cell` (unchanged, machine scope).
- Produces: `run_foundation(roots=None, now=None) -> dict` — same signature, same outputs (foundation.json / FOUNDATION.md), same exit-code rule. Report gains `"stale_repo_exceptions": {repo: [entries]}`; `"unused_exceptions"` now only ever contains central (machine) entries.

- [ ] **Step 1: Update existing foundation tests to the new schema**

In `tests/test_foundation.py`: every fixture PROJECT.md that uses list-form `applicable_standards` would now emit `version-unpinned` violations (the fake standards repos publish versions). Update each fixture frontmatter to map form pinned at `1.0` (e.g. `applicable_standards:\n  project: '1.0'`), add the `standards_env` fixture to every test that calls `run_foundation`, and move exception-based tests from the central-toml pattern to frontmatter `exceptions:` lists (the central file now only matches `_machine` governance findings — a central entry with a repo name matches nothing and shows up as unused). Keep `test_malformed_exceptions_file_propagates` (central file parse errors must still propagate).

- [ ] **Step 2: Add the drift e2e test (exit-criterion demo)**

Append to `tests/test_foundation.py`:

```python
def test_standard_version_bump_shows_drift_in_consumer(
        monkeypatch, make_repo, portfolio_env, standards_env):
    repo = make_repo("consumer", files={"PROJECT.md": (
        "---\nname: consumer\ntier: active\nstatus: active\nversion: 1.0\n"
        "version_source: none\npurpose: p\nupdated: '2026-07-03'\n"
        "foundation: true\nfoundation_contract: 1\n"
        "applicable_standards:\n  project: '1.0'\n"
        "required_checks:\n- id: quality\n  executor: github-actions:quality.yml\n"
        "---\n\n## Backlog\n")})
    wf = repo / ".github" / "workflows" / "quality.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("jobs:\n  quality: {}\n")
    monkeypatch.setattr(
        "portfolio.compliance.checkers.check_project",
        lambda r: CheckResult("project", PASS))
    monkeypatch.setattr(
        "portfolio.checkers.check_governance",
        lambda: CheckResult("governance", PASS))

    report = run_foundation(roots=[repo.parent])
    cell = report["repos"][0]["cells"]["project"]
    assert cell["status"] == PASS and report["exit_code"] == 0

    (standards_env["project"] / "STANDARD_VERSION").write_text("1.1\n")
    report = run_foundation(roots=[repo.parent])
    cell = report["repos"][0]["cells"]["project"]
    assert cell["status"] == VIOLATION
    assert any(d["id"] == "project.version-drift" for d in cell["details"])
    assert report["exit_code"] == 1
```

(Adjust imports/monkeypatch targets to match this file's existing conventions — it already monkeypatches checkers; keep its style. If other foundational fixtures exist in the roots, index `report["repos"]` by name.)

- [ ] **Step 3: Run tests to verify the new/updated ones fail**

Run: `uv run pytest tests/test_foundation.py -q`
Expected: FAIL (foundation.py still resolves exceptions centrally; no `standards_env` wiring; drift not implemented there).

- [ ] **Step 4: Rewrite `run_foundation`**

Replace `src/portfolio/foundation.py` body so it delegates to the core (keep `FoundationError` and `foundational_repos` as-is; delete the local `_PER_REPO_CHECKERS` — it moved to compliance):

```python
import json
from datetime import datetime

from . import checkers, compliance, config, exceptions
from .aggregate import _iter_repos
from .manifest import read_manifest
from .matrix import MACHINE, build_report, render_digest, resolve_cell, summarize


class FoundationError(Exception): ...


def foundational_repos(roots):
    for repo in _iter_repos(roots):
        m = read_manifest(repo)
        if m is None:
            continue
        fm = m.frontmatter
        if "_yaml_error" in fm:
            continue
        if fm.get("foundation") is True:
            yield repo, fm


def run_foundation(roots=None, now=None) -> dict:
    roots = roots or config.DEFAULT_ROOTS
    now = now or datetime.now()

    machine_exc = exceptions.load(config.exceptions_path())

    repos = sorted(foundational_repos(roots), key=lambda pair: pair[0].name)
    if not repos:
        raise FoundationError("no foundational repos found under roots")

    rows, stale_repo_exceptions = compliance.build_rows(repos, now, now.date())

    governance_result = checkers.check_governance()
    machine_cell, used = resolve_cell(governance_result, machine_exc, MACHINE)
    unused_exceptions = [entry for idx, entry in enumerate(machine_exc)
                         if idx not in used]

    summary = summarize(rows, machine_cell)
    generated = now.isoformat(timespec="seconds")
    report = build_report(rows, machine_cell, summary, unused_exceptions, generated)
    report["stale_repo_exceptions"] = stale_repo_exceptions
    digest = render_digest(rows, machine_cell, summary, unused_exceptions, generated,
                           stale_repo_exceptions)

    home = config.portfolio_home()
    home.mkdir(parents=True, exist_ok=True)
    config.foundation_json_path().write_text(json.dumps(report, indent=2))
    config.foundation_digest_path().write_text(digest)

    return report
```

- [ ] **Step 5: Extend `render_digest` for stale frontmatter exceptions + expiry**

In `matrix.py`, give `render_digest` a new optional parameter `stale_repo_exceptions: dict | None = None`. After the existing "Stale exceptions" section append:

```python
    if stale_repo_exceptions:
        lines.append("## Stale frontmatter exceptions (matched nothing — delete or fix)")
        lines.append("")
        for repo, entries in sorted(stale_repo_exceptions.items()):
            for entry in entries:
                lines.append(f"- {repo} / {entry['standard']} / {entry['finding']} — {entry['reason']}")
        lines.append("")
```

Also in the violations detail loop (`_detail_sections`), surface expiry: where a detail line is built, append `" [exception expired {d['exception_expired']}]"` when the key is present:

```python
                suffix = f" [exception expired {d['exception_expired']}]" if d.get("exception_expired") else ""
                sub.append(f"- {d['id']}: {d['message']}{suffix}")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_foundation.py tests/test_matrix.py -q` — all PASS.

- [ ] **Step 7: Update `foundation-exceptions.toml` header**

Replace the comment block so it reads (keep the entry-shape lines, change scope):

```toml
# Accepted exceptions for the MACHINE/governance scope of the foundation matrix.
# Repo-scoped exceptions live in each repo's PROJECT.md frontmatter (`exceptions:`)
# as of WS-1.3 — entries here match ONLY repo = "_machine" governance findings.
#
# Entry shape (all fields except `revisit` required):
#   [[exception]]
#   repo = "_machine"
#   standard = "governance"
#   finding = "governance.check-13*"   # detail id; trailing * globs (fnmatch)
#   reason = "why this is accepted"
#   added = "YYYY-MM-DD"
#   revisit = "trigger that should reopen this"   # recommended
```

- [ ] **Step 8: Full suite + commit**

Run: `uv run pytest tests/ -q`.

```bash
git add src/portfolio/foundation.py src/portfolio/matrix.py foundation-exceptions.toml tests/test_foundation.py
git commit -m "refactor: foundation matrix on shared compliance core; frontmatter exceptions live"
```

---

### Task 8: Portfolio-wide compliance in `scan`

**Files:**
- Modify: `src/portfolio/scan.py`, `src/portfolio/aggregate.py`, `src/portfolio/cli.py`
- Test: `tests/test_scan.py`, `tests/test_aggregate.py`, `tests/test_cli.py` (update/append)

**Interfaces:**
- Consumes: `compliance.build_rows`.
- Produces: `ProjectRecord` gains `compliance: dict = field(default_factory=dict)` (cells as plain dicts `{status, details, note}`, keyed by `COLUMNS`); `scan()` return dict gains `"compliance_violations": int`; PORTFOLIO.md gains a `## Compliance` section; portfolio.json records carry `compliance`.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_scan.py` (reuse its existing fixture style):

```python
def test_scan_attaches_compliance(monkeypatch, make_repo, portfolio_env, standards_env):
    monkeypatch.setattr("portfolio.compliance.checkers.check_project",
                        lambda r: CheckResult("project", PASS))
    declared = make_repo("declared", files={"PROJECT.md": (
        "---\nname: declared\ntier: active\nstatus: active\nversion: 1.0\n"
        "version_source: none\npurpose: p\nupdated: '2026-07-03'\n"
        "applicable_standards:\n  project: '1.0'\n---\n\n## Backlog\n")})
    make_repo("plain", files={"PROJECT.md": (
        "---\nname: plain\ntier: parking\nstatus: idea\npurpose: p\n---\n\n## Backlog\n")})
    make_repo("bare")            # no PROJECT.md

    result = scan(roots=[declared.parent])
    data = json.loads((portfolio_env / "portfolio.json").read_text())
    by_name = {p["name"]: p for p in data["projects"]}
    assert by_name["declared"]["compliance"]["project"]["status"] == "pass"
    assert by_name["plain"]["compliance"]["project"]["status"] == "unknown"
    assert by_name["bare"]["compliance"]["project"]["note"] == "no manifest"
    assert "compliance_violations" in result
    digest = (portfolio_env / "PORTFOLIO.md").read_text()
    assert "## Compliance" in digest
```

(Match this test file's existing imports — it already imports `scan` and uses `portfolio_env`; add `json`, `CheckResult`, `PASS` imports as needed. Note the fixture repo dirs must not collide with `standards_env`'s dot-dirs — they won't; those are dot-prefixed.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scan.py -q`
Expected: FAIL — no `compliance` key in records.

- [ ] **Step 3: Implement**

`src/portfolio/aggregate.py` — add to `ProjectRecord`:

```python
    compliance: dict = field(default_factory=dict)   # column -> {status, details, note}
```

(import `field` from dataclasses). `build_records` is unchanged — compliance is attached by `scan` (aggregation stays checker-free so `portfolio lint`/query paths never pay checker cost).

Add a renderer to `aggregate.py`:

```python
def render_compliance(records) -> str:
    from .matrix import COLUMNS, SYMBOLS, ACCEPTED, VIOLATION, UNKNOWN
    lines = ["## Compliance", "",
             "| name | " + " | ".join(COLUMNS) + " |",
             "|" + "---|" * (len(COLUMNS) + 1)]
    for r in sorted(records, key=lambda x: x.name):
        cells = [r.compliance.get(col, {"status": "unknown"}) for col in COLUMNS]
        lines.append("| " + r.name + " | "
                     + " | ".join(SYMBOLS[c["status"]] for c in cells) + " |")
    accepted = [(r.name, col, d) for r in records
                for col, c in r.compliance.items() if c["status"] == ACCEPTED
                for d in c["details"] if d.get("accepted")]
    if accepted:
        lines += ["", "### Accepted exceptions in effect", ""]
        lines += [f"- {name} / {col} / {d['id']} — {d['exception_reason']}"
                  for name, col, d in accepted]
    return "\n".join(lines) + "\n"
```

`render_digest` in `aggregate.py`: append the compliance section at the end of the returned string:

```python
    return "\n".join(lines) + "\n" + render_compliance(records)
```

`src/portfolio/scan.py` — attach compliance between building records and writing outputs:

```python
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from . import compliance, config
from .aggregate import build_records, to_json, render_digest
from .inbox import read_inbox
from .manifest import read_manifest
from .matrix import VIOLATION


def scan(roots=None, today: date | None = None, now: datetime | None = None) -> dict:
    roots = roots or config.DEFAULT_ROOTS
    today = today or date.today()
    now = now or datetime.now()
    records = build_records(roots, today=today)

    pairs = []
    for record in records:
        m = read_manifest(Path(record.path))
        # fm=None only when the manifest is missing; a YAML-error frontmatter is
        # passed through so build_rows can note "frontmatter unreadable".
        pairs.append((Path(record.path), m.frontmatter if m else None))
    rows, _stale = compliance.build_rows(pairs, now, today)
    for record, row in zip(records, rows):
        record.compliance = {col: asdict(cell) for col, cell in row.cells.items()}

    untriaged_count = sum(1 for i in read_inbox() if i.status == "untriaged")
    home = config.portfolio_home()
    home.mkdir(parents=True, exist_ok=True)
    config.json_path().write_text(to_json(records, untriaged_count))
    config.digest_path().write_text(render_digest(records, untriaged_count))
    fails = sum(1 for r in records for f in r.findings if f["severity"] == "FAIL")
    warns = sum(1 for r in records for f in r.findings if f["severity"] == "WARN")
    compliance_violations = sum(
        1 for r in records for c in r.compliance.values() if c["status"] == VIOLATION)
    return {"projects": len(records), "fails": fails, "warns": warns,
            "compliance_violations": compliance_violations}
```

(`build_rows` preserves input order, so `zip(records, rows)` is aligned; both derive from the same `records` list.)

`cli.py`: no change needed (it already prints `json.dumps(scan(...))`, which now includes the new key). Update any `test_cli.py` assertion on scan output keys.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scan.py tests/test_aggregate.py tests/test_cli.py -q` — all PASS. Check `test_aggregate.py`/`test_e2e.py` for asdict-shape assertions and update for the new `compliance` key.

- [ ] **Step 5: Full suite + commit**

Run: `uv run pytest tests/ -q`.

```bash
git add src/portfolio/scan.py src/portfolio/aggregate.py tests/
git commit -m "feat: portfolio-wide compliance matrix in portfolio scan"
```

---

### Task 9: Migration — STANDARD_VERSION files + 8 foundation-repo contracts

This task edits OTHER repos. Each repo: its own branch `chore/ws13-foundation-contract`, commit, push, PR. **Do not merge any PR — Devon merges.** project-standards' own PROJECT.md is edited on our existing branch.

**Files (per repo):** `PROJECT.md`; plus `STANDARD_VERSION` in security-standards and code-standards.

- [ ] **Step 1: STANDARD_VERSION in the two other standards repos**

```bash
cd ~/Projects/security-standards && git checkout -b chore/ws13-foundation-contract
printf '1.0\n' > STANDARD_VERSION
cd ~/Developer/code-standards && git checkout -b chore/ws13-foundation-contract
printf '1.0\n' > STANDARD_VERSION
```

(Committed with each repo's frontmatter change in Step 3.)

- [ ] **Step 2: Determine truthful required_checks per repo**

Verified wiring as of 2026-07-03 (re-verify with `ls <repo>/.github/workflows/` before writing; use the actual job name from each workflow — `rtk proxy grep -A1 '^jobs:' <wf>`):

| repo | required_checks to declare |
|---|---|
| project-standards | `quality` → `github-actions:quality.yml`; `portfolio-scan` → `launchagent:com.devon.portfolio-scan` |
| security-standards | `quality` → `github-actions:quality.yml`; `security-scan` → `github-actions:security-scan.yml`; `session-scan-gate` → `hook:bws-scan-gate.sh`; `weekly-scan` → `launchagent:com.devon.security-scan`; `factory-events-nightly` → `launchagent:com.devon.factory-events` |
| code-standards | `quality` → `github-actions:quality.yml` |
| change-manager | `quality` → `github-actions:quality.yml`; `change-window` → `launchagent:com.devon.change-window` |
| infraops-mcp-server | `quality` → `github-actions:quality.yml` |
| brain | `quality` → `github-actions:quality.yml`; `ci` → `github-actions:ci.yml` |
| vps-backup | `backup-run` → `launchagent:com.devon.vps-backup`; `backup-verify` → `launchagent:com.devon.vps-backup-verify` |
| alobar-id | none wired → declare NOTHING; the resulting `checks.none-declared` violation is the honest work list, per spec §6. Do NOT add an exception to mask it. |

Note on security-standards `quality`: it is wired-but-hollow (`make check` has no target — known repo invariant). Static wiring passes it; that is the spec §4 stated limitation, declare it anyway.

- [ ] **Step 3: Upgrade each repo's frontmatter**

For each of the 8 repos, edit ONLY the frontmatter keys (preserve everything else, including `coolify_resources` where present). Transform:

```yaml
# from (WS-0.0 form)
foundation: true
applicable_standards:
- project
- security
- code
# to (WS-1.3 form) — keep the SAME set of standards, do not add or remove any
foundation: true
foundation_contract: 1
applicable_standards:
  project: '1.0'
  security: '1.0'
  code: '1.0'
required_checks:
- id: quality
  executor: github-actions:quality.yml
# (per the Step-2 table; omit required_checks entirely for alobar-id)
```

Rules: `infra` (where present) maps to `infra: null` (render as `infra:` or `infra: null`). Pin every versioned standard at `'1.0'` (quoted — YAML would read 1.0 as a float). No `exceptions:` blocks anywhere — existing violations stay visible (they're WS-0.3's work list).

Per external repo:

```bash
cd <repo> && git checkout -b chore/ws13-foundation-contract   # already done for the two standards repos
# edit PROJECT.md (+ STANDARD_VERSION already created where applicable)
git add PROJECT.md STANDARD_VERSION 2>/dev/null || git add PROJECT.md
git commit -m "chore: WS-1.3 foundation_contract (versions + required_checks)"
git push -u origin chore/ws13-foundation-contract
gh pr create --title "chore: WS-1.3 foundation_contract" --body "Pins standard versions, declares required_checks per project-standards WS-1.3 (spec: project-standards docs/superpowers/specs/2026-07-03-ws13-foundation-contract-design.md).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_0182VMhMAuBf1i6bRQVkGHWg"
```

For project-standards itself: edit PROJECT.md on `feat/ws13-foundation-contract` and commit (no separate PR).

- [ ] **Step 4: Verify the live matrix**

```bash
cd ~/Projects/project-standards
uv run portfolio foundation
```

Expected: 8 repos; the `checks` column green everywhere except alobar-id (`checks.none-declared`); project/security/code columns match pre-WS-1.3 state (same pass/violation pattern as the last FOUNDATION.md — version pins are current so no drift findings); no stale-exception noise. Read `~/.portfolio/FOUNDATION.md` and eyeball the table. NOTE: the external-repo edits are on unmerged branches — run the check with those branches checked out locally (they are, from Step 3); state in the PR/summary that post-merge FOUNDATION.md is the durable evidence.

- [ ] **Step 5: Commit project-standards changes**

```bash
git add PROJECT.md
git commit -m "chore: adopt foundation_contract in own manifest"
```

---

### Task 10: Docs, backlog follow-ups, final verification

**Files:**
- Modify: `README.md` (project-standards)
- Test: full gates

- [ ] **Step 1: Update README**

In the README's CLI/scan documentation sections: document the contract frontmatter (copy the schema block from spec §2), the five+checks matrix columns, `STANDARD_VERSION` semantics (acknowledgment, not behavior selector), exceptions-in-frontmatter with `review_by` expiry, the machine-scope-only central toml, and the scan compliance section. Keep the existing structure; add a `## foundation_contract` subsection rather than rewriting.

- [ ] **Step 2: File the three bump-guard backlog items**

```bash
cd ~/Projects/project-standards
uv run portfolio add --repo ~/Projects/project-standards --priority P2 "CI guard: STANDARD_VERSION must be bumped when the standard's rules change in a diff (WS-1.3 follow-up; without it versioning rusts silently)"
uv run portfolio add --repo ~/Projects/security-standards --priority P2 "CI guard: STANDARD_VERSION must be bumped when the standard's rules change in a diff (WS-1.3 follow-up)"
uv run portfolio add --repo ~/Developer/code-standards --priority P2 "CI guard: STANDARD_VERSION must be bumped when the standard's rules change in a diff (WS-1.3 follow-up)"
```

(Backlog edits to the two external repos land on their open `chore/ws13-foundation-contract` branches — amend/commit + push so the PRs carry them.)

- [ ] **Step 3: Final gates**

```bash
cd ~/Projects/project-standards
make check                      # lint + type + tests: must be green
uv run portfolio foundation     # exit code + digest sane
uv run portfolio scan           # LaunchAgent-equivalent weekly run: must succeed
```

Then run `/code-review` on the branch diff and fix findings. Confirm `~/.portfolio/PORTFOLIO.md` contains the Compliance section with ~45+ rows and PLAUSIBLE unknown counts (most repos undeclared — that is correct).

- [ ] **Step 4: Commit + summarize**

```bash
git add README.md PROJECT.md
git commit -m "docs: foundation_contract README + WS-1.3 follow-up backlog items"
```

Summarize for Devon: PRs opened (list), FOUNDATION.md/PORTFOLIO.md state, the alobar-id finding, and that merges await his signal.
