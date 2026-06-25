# Project Standards (portfolio toolkit) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `portfolio` CLI + `backlog` capture skill + weekly scanner that make a repo-local `PROJECT.md` the single source of truth for project state/backlog across ~52 repos, with capture that always succeeds via a central inbox.

**Architecture:** A zero-install Python package (`src/` layout, run via `PYTHONPATH=… python3 -m portfolio.cli`, exactly like `security-standards`). A pure validator is the shared core, consumed by `init`, `add`, `triage`, `scan`, and a session hook. Capture writes to `~/.portfolio/inbox.jsonl` first and write-throughs to `PROJECT.md` only when the repo is unambiguous and the tree is clean. Derived views (`portfolio.json`, `PORTFOLIO.md`) are regenerated, never committed.

**Tech Stack:** Python 3.12 (stdlib `tomllib`, `json`, `subprocess`, `dataclasses`, `pathlib`, `hashlib`, `datetime`), PyYAML for frontmatter, pytest for tests. Bash for the LaunchAgent wrapper + Stop hook. No network deps.

## Global Constraints

- Python **3.12+** (uses stdlib `tomllib`). One third-party runtime dep only: **PyYAML**.
- Invocation pattern: `PYTHONPATH="$HOME/Projects/project-standards/src" python3 -m portfolio.cli <subcommand>` (mirror of `security_scan`).
- Source of truth is the repo's `PROJECT.md`. The CLI **never runs `git init`** and **never rewrites or reorders existing `## Backlog` lines** (append-only).
- Derived artifacts live in `~/.portfolio/` (`inbox.jsonl`, `portfolio.json`, `PORTFOLIO.md`) and are **never committed**.
- Manifest filename is exactly `PROJECT.md` at repo root.
- `tier ∈ {active, parking}`; `status ∈ {idea, in-progress, active, archived}`; `version_source ∈ {package.json, pyproject, cargo, git-tag, none}`.
- Required frontmatter — active: `name, tier, status, version, version_source, purpose, updated`; parking: `name, tier, status, purpose`.
- Thresholds: manifest "stale" if `updated` is **> 30 days** behind git HEAD date; backlog item "aged" if `added` is **> 180 days** old.
- TDD: every task is failing-test → minimal impl → passing-test → commit. Commit messages end with the two trailers from CLAUDE.md (Co-Authored-By + Claude-Session). Tests must not touch the real `~/.portfolio` or real repos — use `tmp_path` and a `PORTFOLIO_DIR` override via env var `PORTFOLIO_HOME`.

---

## File Structure

```
project-standards/
  pyproject.toml                         # package metadata + PyYAML dep + pytest config
  src/portfolio/
    __init__.py
    config.py        # paths (PORTFOLIO_HOME override), default roots, thresholds
    schema.py        # constants + Finding + validate_frontmatter() (pure)
    manifest.py      # parse/render PROJECT.md, parse_backlog(), append_backlog_item()
    detect.py        # name/version/remote/is_git/purpose detection
    validator.py     # lint(repo) -> list[Finding]  (the shared core)
    init.py          # init_repo() idempotent scaffold/repair
    inbox.py         # InboxItem + jsonl read/append/mark_triaged + new_id
    add.py           # add_item() capture: inbox-first + conditional write-through
    triage.py        # untriaged()/assign()
    aggregate.py     # ProjectRecord, build_records(), to_json(), render_digest()
    scan.py          # scan(roots) -> writes json + digest
    query.py         # query(filters) over portfolio.json
    cli.py           # argparse dispatch
  tests/
    conftest.py      # fixtures: tmp portfolio home, fake git repo builder
    test_schema.py test_manifest.py test_detect.py test_validator.py
    test_init.py test_inbox.py test_add.py test_triage.py
    test_aggregate.py test_scan.py test_query.py test_cli.py
  integrations/
    backlog.skill.md                     # the capture skill (install to ~/.claude/skills)
    portfolio-nudge.sh                   # Stop hook
    com.devon.portfolio-scan.plist       # weekly LaunchAgent
    install.sh                           # symlink/copy integrations into place
  README.md                              # THE STANDARD (human + agent facing)
```

Each `portfolio/*.py` has one responsibility; `validator.py` is the only module that composes the others. `cli.py` is thin dispatch — no logic lives there.

---

### Task 1: Package scaffold + config

**Files:**
- Create: `pyproject.toml`, `src/portfolio/__init__.py`, `src/portfolio/config.py`
- Create: `tests/conftest.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `config.portfolio_home() -> Path`, `config.INBOX_PATH/JSON_PATH/DIGEST_PATH` (computed from home), `config.DEFAULT_ROOTS: list[Path]`, `config.STALE_DAYS=30`, `config.BACKLOG_AGE_DAYS=180`.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "portfolio"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["PyYAML>=6.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 2: Write the failing test** in `tests/test_config.py`

```python
import os
from pathlib import Path
from portfolio import config

def test_portfolio_home_defaults_to_dot_portfolio(monkeypatch):
    monkeypatch.delenv("PORTFOLIO_HOME", raising=False)
    assert config.portfolio_home() == Path.home() / ".portfolio"

def test_portfolio_home_respects_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PORTFOLIO_HOME", str(tmp_path))
    assert config.portfolio_home() == tmp_path
    assert config.inbox_path() == tmp_path / "inbox.jsonl"
```

- [ ] **Step 3: Run test, verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'portfolio.config'`

- [ ] **Step 4: Implement `src/portfolio/__init__.py` (empty) and `src/portfolio/config.py`**

```python
import os
from pathlib import Path

DEFAULT_ROOTS = [Path.home() / "Projects", Path.home() / "Developer"]
STALE_DAYS = 30
BACKLOG_AGE_DAYS = 180

def portfolio_home() -> Path:
    override = os.environ.get("PORTFOLIO_HOME")
    return Path(override) if override else Path.home() / ".portfolio"

def inbox_path() -> Path:
    return portfolio_home() / "inbox.jsonl"

def json_path() -> Path:
    return portfolio_home() / "portfolio.json"

def digest_path() -> Path:
    return portfolio_home() / "PORTFOLIO.md"
```

- [ ] **Step 5: Write `tests/conftest.py` shared fixtures**

```python
import subprocess
from pathlib import Path
import pytest

@pytest.fixture
def portfolio_env(monkeypatch, tmp_path):
    # leading dot so the scanner (which skips dotted dirs) never counts the
    # portfolio home as a project when tmp_path doubles as a scan root.
    home = tmp_path / ".portfolio_home"
    home.mkdir()
    monkeypatch.setenv("PORTFOLIO_HOME", str(home))
    return home

@pytest.fixture
def make_repo(tmp_path):
    def _make(name, git=True, files=None):
        repo = tmp_path / name
        repo.mkdir()
        for rel, content in (files or {}).items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        if git:
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
            subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                            "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
        return repo
    return _make
```

- [ ] **Step 6: Run tests, verify pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 passed)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/portfolio tests
git commit -m "feat: package scaffold + config (paths, roots, thresholds)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 2: Schema + pure frontmatter validator

**Files:**
- Create: `src/portfolio/schema.py`, `tests/test_schema.py`

**Interfaces:**
- Produces: `Finding(severity: str, code: str, message: str)` dataclass (`severity ∈ {"FAIL","WARN"}`); `validate_frontmatter(fm: dict) -> list[Finding]`; constants `TIERS, STATUSES, VERSION_SOURCES, REQUIRED_ACTIVE, REQUIRED_PARKING`.

- [ ] **Step 1: Write the failing test**

```python
from portfolio.schema import validate_frontmatter, Finding

def test_valid_active_frontmatter_has_no_findings():
    fm = {"name": "x", "tier": "active", "status": "active",
          "version": "1.0.0", "version_source": "npm".replace("npm","package.json"),
          "purpose": "does x", "updated": "2026-06-25"}
    assert validate_frontmatter(fm) == []

def test_missing_required_active_field_is_fail():
    fm = {"name": "x", "tier": "active", "status": "active",
          "version": "1.0.0", "version_source": "package.json", "purpose": "x"}
    findings = validate_frontmatter(fm)
    assert any(f.code == "missing_field" and "updated" in f.message and f.severity == "FAIL"
               for f in findings)

def test_parking_does_not_require_version():
    fm = {"name": "x", "tier": "parking", "status": "idea", "purpose": "x"}
    assert validate_frontmatter(fm) == []

def test_bad_enum_is_fail():
    fm = {"name": "x", "tier": "parking", "status": "bogus", "purpose": "x"}
    assert any(f.code == "bad_enum" and f.severity == "FAIL"
               for f in validate_frontmatter(fm))
```

- [ ] **Step 2: Run test, verify fails**

Run: `pytest tests/test_schema.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/portfolio/schema.py`**

```python
from dataclasses import dataclass

TIERS = {"active", "parking"}
STATUSES = {"idea", "in-progress", "active", "archived"}
VERSION_SOURCES = {"package.json", "pyproject", "cargo", "git-tag", "none"}
REQUIRED_ACTIVE = ["name", "tier", "status", "version", "version_source", "purpose", "updated"]
REQUIRED_PARKING = ["name", "tier", "status", "purpose"]

@dataclass(frozen=True)
class Finding:
    severity: str  # "FAIL" | "WARN"
    code: str
    message: str

def validate_frontmatter(fm: dict) -> list[Finding]:
    findings: list[Finding] = []
    tier = fm.get("tier")
    if tier not in TIERS:
        findings.append(Finding("FAIL", "bad_enum", f"tier must be one of {sorted(TIERS)}, got {tier!r}"))
        required = REQUIRED_PARKING  # fall back to lenient set so we still report other gaps
    else:
        required = REQUIRED_ACTIVE if tier == "active" else REQUIRED_PARKING
    for field in required:
        if not fm.get(field):
            findings.append(Finding("FAIL", "missing_field", f"missing required field: {field}"))
    if fm.get("status") and fm["status"] not in STATUSES:
        findings.append(Finding("FAIL", "bad_enum", f"status must be one of {sorted(STATUSES)}, got {fm['status']!r}"))
    if fm.get("version_source") and fm["version_source"] not in VERSION_SOURCES:
        findings.append(Finding("FAIL", "bad_enum", f"version_source invalid: {fm['version_source']!r}"))
    return findings
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_schema.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/schema.py tests/test_schema.py
git commit -m "feat: PROJECT.md frontmatter schema + pure validator

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 3: Manifest read/render + append-only backlog

**Files:**
- Create: `src/portfolio/manifest.py`, `tests/test_manifest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Manifest(frontmatter: dict, body: str, path: Path)`; `read_manifest(repo: Path) -> Manifest | None`; `write_manifest(m: Manifest) -> None`; `parse_backlog(body: str) -> list[BacklogItem]` where `BacklogItem(text: str, priority: str|None, added: str|None, raw: str, malformed: bool)`; `append_backlog_item(repo: Path, text: str, priority: str|None, added: str) -> None`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from portfolio.manifest import (read_manifest, write_manifest, Manifest,
                                parse_backlog, append_backlog_item)

MANIFEST = """---
name: demo
tier: active
status: active
version: 1.2.0
version_source: package.json
purpose: demo thing
updated: 2026-06-01
---

## Backlog
- [ ] (P2) existing item — added 2026-05-01

## Future plans
later
"""

def test_round_trip_preserves_frontmatter_and_body(tmp_path):
    (tmp_path / "PROJECT.md").write_text(MANIFEST)
    m = read_manifest(tmp_path)
    assert m.frontmatter["name"] == "demo"
    assert "Future plans" in m.body
    write_manifest(m)
    assert read_manifest(tmp_path).frontmatter["version"] == "1.2.0"

def test_parse_backlog_extracts_priority_and_date(tmp_path):
    (tmp_path / "PROJECT.md").write_text(MANIFEST)
    items = parse_backlog(read_manifest(tmp_path).body)
    assert items[0].priority == "P2"
    assert items[0].added == "2026-05-01"
    assert items[0].malformed is False

def test_append_is_additive_and_preserves_existing_lines(tmp_path):
    (tmp_path / "PROJECT.md").write_text(MANIFEST)
    append_backlog_item(tmp_path, "new thing", "P1", "2026-06-25")
    body = (tmp_path / "PROJECT.md").read_text()
    assert "existing item" in body          # old line untouched
    assert "(P1) new thing — added 2026-06-25" in body
    assert "## Future plans" in body         # other sections intact

def test_read_missing_returns_none(tmp_path):
    assert read_manifest(tmp_path) is None
```

- [ ] **Step 2: Run test, verify fails**

Run: `pytest tests/test_manifest.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/portfolio/manifest.py`**

```python
import re
from dataclasses import dataclass
from pathlib import Path
import yaml

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
BACKLOG_LINE_RE = re.compile(
    r"^- \[[ xX]\] (?:\((?P<priority>P\d)\) )?(?P<text>.*?)(?: — added (?P<added>\d{4}-\d{2}-\d{2}))?\s*$"
)

@dataclass
class Manifest:
    frontmatter: dict
    body: str
    path: Path

@dataclass
class BacklogItem:
    text: str
    priority: str | None
    added: str | None
    raw: str
    malformed: bool

def parse_frontmatter(text: str) -> tuple[dict, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    fm = yaml.safe_load(match.group(1)) or {}
    return fm, match.group(2)

def render(fm: dict, body: str) -> str:
    front = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False).rstrip("\n")
    return f"---\n{front}\n---\n\n{body.lstrip(chr(10))}"

def read_manifest(repo: Path) -> Manifest | None:
    path = repo / "PROJECT.md"
    if not path.exists():
        return None
    fm, body = parse_frontmatter(path.read_text())
    return Manifest(frontmatter=fm, body=body, path=path)

def write_manifest(m: Manifest) -> None:
    m.path.write_text(render(m.frontmatter, m.body))

def parse_backlog(body: str) -> list[BacklogItem]:
    items: list[BacklogItem] = []
    in_section = False
    for line in body.splitlines():
        if line.strip().lower() == "## backlog":
            in_section = True
            continue
        if line.startswith("## ") and in_section:
            break
        if in_section and line.strip().startswith("- ["):
            m = BACKLOG_LINE_RE.match(line.rstrip())
            if m:
                items.append(BacklogItem(m.group("text").strip(), m.group("priority"),
                                         m.group("added"), line, malformed=False))
            else:
                items.append(BacklogItem(line.strip(), None, None, line, malformed=True))
    return items

def append_backlog_item(repo: Path, text: str, priority: str | None, added: str) -> None:
    path = repo / "PROJECT.md"
    content = path.read_text()
    prefix = f"({priority}) " if priority else ""
    new_line = f"- [ ] {prefix}{text} — added {added}"
    lines = content.splitlines()
    out, inserted = [], False
    for i, line in enumerate(lines):
        out.append(line)
        if not inserted and line.strip().lower() == "## backlog":
            # insert after any existing backlog lines (append-only, preserve order)
            j = i + 1
            while j < len(lines) and (lines[j].strip().startswith("- [") or not lines[j].strip()):
                out.append(lines[j]); j += 1
            out.append(new_line)
            inserted = True
            out.extend(lines[j:])
            break
    if not inserted:
        out += ["", "## Backlog", new_line]
    path.write_text("\n".join(out) + ("\n" if content.endswith("\n") else ""))
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_manifest.py -v`
Expected: PASS (4 passed). If `test_append_is_additive` fails on ordering, confirm the insert loop appends the new line *after* the existing backlog block.

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/manifest.py tests/test_manifest.py
git commit -m "feat: PROJECT.md parse/render + append-only backlog writer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 4: Detection (name/version/remote/git/purpose)

**Files:**
- Create: `src/portfolio/detect.py`, `tests/test_detect.py`

**Interfaces:**
- Produces: `detect_name(repo: Path) -> str`; `detect_version(repo: Path) -> tuple[str, str]` returning `(version, source)` where source ∈ VERSION_SOURCES; `is_git(repo: Path) -> bool`; `detect_remote(repo: Path) -> str | None`; `detect_purpose(repo: Path) -> str | None`.

- [ ] **Step 1: Write the failing test**

```python
from portfolio.detect import detect_name, detect_version, is_git, detect_purpose

def test_version_from_package_json(make_repo):
    repo = make_repo("p", files={"package.json": '{"version": "3.4.5"}'})
    assert detect_version(repo) == ("3.4.5", "package.json")

def test_version_from_pyproject(make_repo):
    repo = make_repo("p", files={"pyproject.toml": '[project]\nversion = "2.0.1"\n'})
    assert detect_version(repo) == ("2.0.1", "pyproject")

def test_version_none_when_undetectable(make_repo):
    repo = make_repo("p", files={"README.md": "hi"})
    assert detect_version(repo) == ("n/a", "none")

def test_name_is_dir_name(make_repo):
    assert detect_name(make_repo("contacts")) == "contacts"

def test_is_git_true_false(make_repo):
    assert is_git(make_repo("g", git=True)) is True
    assert is_git(make_repo("ng", git=False)) is False

def test_purpose_from_readme_first_prose_line(make_repo):
    repo = make_repo("p", files={"README.md": "# Title\n\nDoes the thing well.\n"})
    assert detect_purpose(repo) == "Does the thing well."
```

- [ ] **Step 2: Run test, verify fails**

Run: `pytest tests/test_detect.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/portfolio/detect.py`**

```python
import json
import subprocess
import tomllib
from pathlib import Path

def detect_name(repo: Path) -> str:
    return repo.name

def is_git(repo: Path) -> bool:
    return (repo / ".git").exists()

def detect_version(repo: Path) -> tuple[str, str]:
    pkg = repo / "package.json"
    if pkg.exists():
        try:
            v = json.loads(pkg.read_text()).get("version")
            if v:
                return str(v), "package.json"
        except json.JSONDecodeError:
            pass
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
            v = data.get("project", {}).get("version") or data.get("tool", {}).get("poetry", {}).get("version")
            if v:
                return str(v), "pyproject"
        except tomllib.TOMLDecodeError:
            pass
    cargo = repo / "Cargo.toml"
    if cargo.exists():
        try:
            v = tomllib.loads(cargo.read_text()).get("package", {}).get("version")
            if v:
                return str(v), "cargo"
        except tomllib.TOMLDecodeError:
            pass
    if is_git(repo):
        tag = _git(repo, ["describe", "--tags", "--abbrev=0"])
        if tag:
            return tag, "git-tag"
    return "n/a", "none"

def detect_remote(repo: Path) -> str | None:
    if not is_git(repo):
        return None
    return _git(repo, ["remote", "get-url", "origin"]) or None

def detect_purpose(repo: Path) -> str | None:
    readme = repo / "README.md"
    if not readme.exists():
        return None
    for line in readme.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith("#") and not s.startswith("!") and not s.startswith("["):
            return s
    return None

def _git(repo: Path, args: list[str]) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else None
    except (subprocess.SubprocessError, OSError):
        return None
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_detect.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/detect.py tests/test_detect.py
git commit -m "feat: project metadata detection (name/version/remote/git/purpose)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 5: Validator (the shared core)

**Files:**
- Create: `src/portfolio/validator.py`, `tests/test_validator.py`

**Interfaces:**
- Consumes: `schema.validate_frontmatter`, `manifest.read_manifest/parse_backlog`, `detect.is_git`, `config.STALE_DAYS/BACKLOG_AGE_DAYS`.
- Produces: `lint(repo: Path, today: date | None = None) -> list[Finding]`. Empty list ⇒ OK. `today` is injectable for deterministic tests.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from portfolio.validator import lint

def test_missing_manifest_is_fail(make_repo):
    findings = lint(make_repo("x"))
    assert any(f.code == "missing_manifest" and f.severity == "FAIL" for f in findings)

def test_conforming_active_repo_is_clean(make_repo):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\n"
            "version_source: package.json\npurpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n")
    repo = make_repo("x", files={"PROJECT.md": body, "package.json": '{"version":"1.0.0"}'})
    assert lint(repo, today=date(2026, 6, 26)) == []

def test_non_git_active_is_fail(make_repo):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: n/a\n"
            "version_source: none\npurpose: p\nupdated: 2026-06-25\n---\n")
    repo = make_repo("x", git=False, files={"PROJECT.md": body})
    assert any(f.code == "not_git" and f.severity == "FAIL" for f in lint(repo, today=date(2026,6,26)))

def test_aged_backlog_item_is_warn(make_repo):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: n/a\n"
            "version_source: none\npurpose: p\nupdated: 2026-06-25\n---\n\n"
            "## Backlog\n- [ ] (P3) old — added 2025-01-01\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    assert any(f.code == "aged_item" and f.severity == "WARN" for f in lint(repo, today=date(2026,6,26)))
```

- [ ] **Step 2: Run test, verify fails**

Run: `pytest tests/test_validator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/portfolio/validator.py`**

```python
from datetime import date, datetime
from pathlib import Path

from . import config
from .schema import Finding, validate_frontmatter
from .manifest import read_manifest, parse_backlog
from .detect import is_git

def lint(repo: Path, today: date | None = None) -> list[Finding]:
    today = today or date.today()
    m = read_manifest(repo)
    if m is None:
        return [Finding("FAIL", "missing_manifest", f"{repo.name}: no PROJECT.md")]
    findings = list(validate_frontmatter(m.frontmatter))
    tier = m.frontmatter.get("tier")
    if not is_git(repo):
        sev = "FAIL" if tier == "active" else "WARN"
        findings.append(Finding(sev, "not_git", f"{repo.name}: not a git repo"))
    for item in parse_backlog(m.body):
        if item.malformed:
            findings.append(Finding("WARN", "malformed_item", f"{repo.name}: malformed backlog line: {item.raw.strip()}"))
        elif item.added:
            try:
                age = (today - datetime.strptime(item.added, "%Y-%m-%d").date()).days
                if age > config.BACKLOG_AGE_DAYS:
                    findings.append(Finding("WARN", "aged_item", f"{repo.name}: backlog item {age}d old: {item.text}"))
            except ValueError:
                findings.append(Finding("WARN", "malformed_item", f"{repo.name}: bad added-date: {item.raw.strip()}"))
    return findings
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_validator.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/validator.py tests/test_validator.py
git commit -m "feat: validator core (manifest/git/backlog findings)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

> **NOTE — deferred WARN:** the spec's "manifest stale vs git HEAD" and "App Brain ⇄ purpose divergence" checks are intentionally **not** in this task. Stale-vs-HEAD needs a git-date lookup added in Task 9 (aggregate, where HEAD date is already fetched); App Brain divergence is deferred to Phase 3 (no CLI access to the MCP). Do not add a placeholder for it.

---

### Task 6: `init` — idempotent scaffold/repair

**Files:**
- Create: `src/portfolio/init.py`, `tests/test_init.py`

**Interfaces:**
- Consumes: `detect.*`, `manifest.read_manifest/write_manifest/Manifest`.
- Produces: `init_repo(repo: Path, tier: str = "active", today: date | None = None) -> Manifest`. Idempotent: fills only blank/missing frontmatter fields, never overwrites human values, never runs `git init`. Preserves existing body.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from portfolio.init import init_repo
from portfolio.manifest import read_manifest

def test_init_creates_conforming_manifest(make_repo):
    repo = make_repo("contacts", files={"package.json": '{"version":"0.4.2"}',
                                         "README.md": "# Contacts\n\nContact hub.\n"})
    init_repo(repo, today=date(2026, 6, 25))
    fm = read_manifest(repo).frontmatter
    assert fm["name"] == "contacts"
    assert fm["version"] == "0.4.2" and fm["version_source"] == "package.json"
    assert fm["purpose"] == "Contact hub."
    assert fm["updated"] == "2026-06-25"
    assert fm["tier"] == "active"

def test_init_does_not_clobber_human_fields(make_repo):
    body = ("---\nname: contacts\ntier: active\nstatus: active\nversion: 9.9.9\n"
            "version_source: package.json\npurpose: HAND WRITTEN\nupdated: 2026-01-01\n---\n\n## Backlog\n- [ ] (P1) keep me — added 2026-01-01\n")
    repo = make_repo("contacts", files={"PROJECT.md": body, "package.json": '{"version":"0.4.2"}'})
    init_repo(repo, today=date(2026, 6, 25))
    fm = read_manifest(repo).frontmatter
    assert fm["purpose"] == "HAND WRITTEN"   # not clobbered
    assert fm["version"] == "9.9.9"          # not clobbered
    assert "keep me" in read_manifest(repo).body

def test_init_never_creates_git(make_repo):
    repo = make_repo("scratch", git=False)
    init_repo(repo, tier="parking", today=date(2026, 6, 25))
    assert not (repo / ".git").exists()
```

- [ ] **Step 2: Run test, verify fails**

Run: `pytest tests/test_init.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/portfolio/init.py`**

```python
from datetime import date
from pathlib import Path

from . import detect
from .manifest import Manifest, read_manifest, write_manifest

ACTIVE_BODY = "## Backlog\n\n## Future plans\n"
PARKING_BODY = ""

def init_repo(repo: Path, tier: str = "active", today: date | None = None) -> Manifest:
    today = today or date.today()
    existing = read_manifest(repo)
    fm = dict(existing.frontmatter) if existing else {}
    body = existing.body if existing else (ACTIVE_BODY if tier == "active" else PARKING_BODY)

    fm.setdefault("name", detect.detect_name(repo))
    fm.setdefault("tier", tier)
    fm.setdefault("status", "in-progress")
    fm.setdefault("purpose", detect.detect_purpose(repo) or "TODO: one-line purpose")
    if fm.get("tier") == "active":
        if not fm.get("version"):
            version, source = detect.detect_version(repo)
            fm["version"] = version
            fm["version_source"] = source
        fm.setdefault("version_source", "none")
        fm.setdefault("updated", today.isoformat())

    m = Manifest(frontmatter=fm, body=body, path=repo / "PROJECT.md")
    write_manifest(m)
    return m
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_init.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/init.py tests/test_init.py
git commit -m "feat: idempotent init (scaffold/repair, no clobber, no git init)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 7: Inbox store

**Files:**
- Create: `src/portfolio/inbox.py`, `tests/test_inbox.py`

**Interfaces:**
- Consumes: `config.inbox_path`.
- Produces: `InboxItem(id, ts, text, inferred_repo, confidence, source_session, priority, status)` dataclass; `new_id(text: str, ts: str) -> str` (deterministic 12-char hash for dedup); `append_inbox(item: InboxItem) -> None`; `read_inbox() -> list[InboxItem]`; `mark_triaged(item_id: str) -> None`; `find_duplicate(text: str) -> InboxItem | None`.

- [ ] **Step 1: Write the failing test**

```python
from portfolio.inbox import InboxItem, append_inbox, read_inbox, mark_triaged, new_id, find_duplicate

def _item(text="do x", repo=None, conf=0.0, status="untriaged"):
    return InboxItem(id=new_id(text, "2026-06-25T10:00:00"), ts="2026-06-25T10:00:00",
                     text=text, inferred_repo=repo, confidence=conf,
                     source_session="s1", priority=None, status=status)

def test_append_and_read_roundtrip(portfolio_env):
    append_inbox(_item("alpha"))
    append_inbox(_item("beta"))
    texts = [i.text for i in read_inbox()]
    assert texts == ["alpha", "beta"]

def test_mark_triaged_updates_status(portfolio_env):
    it = _item("gamma")
    append_inbox(it)
    mark_triaged(it.id)
    assert read_inbox()[0].status == "triaged"

def test_find_duplicate_matches_same_text(portfolio_env):
    append_inbox(_item("same text"))
    assert find_duplicate("same text") is not None
    assert find_duplicate("different") is None
```

- [ ] **Step 2: Run test, verify fails**

Run: `pytest tests/test_inbox.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/portfolio/inbox.py`**

```python
import hashlib
import json
from dataclasses import dataclass, asdict

from . import config

@dataclass
class InboxItem:
    id: str
    ts: str
    text: str
    inferred_repo: str | None
    confidence: float
    source_session: str | None
    priority: str | None
    status: str  # "untriaged" | "triaged"

def new_id(text: str, ts: str) -> str:
    return hashlib.sha256(f"{text}|{ts}".encode()).hexdigest()[:12]

def append_inbox(item: InboxItem) -> None:
    path = config.inbox_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(item)) + "\n")

def read_inbox() -> list[InboxItem]:
    path = config.inbox_path()
    if not path.exists():
        return []
    items: dict[str, InboxItem] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            items[d["id"]] = InboxItem(**d)   # later lines (status updates) win
    return list(items.values())

def mark_triaged(item_id: str) -> None:
    for item in read_inbox():
        if item.id == item_id:
            item.status = "triaged"
            append_inbox(item)
            return

def find_duplicate(text: str) -> InboxItem | None:
    norm = text.strip().lower()
    for item in read_inbox():
        if item.text.strip().lower() == norm and item.status == "untriaged":
            return item
    return None
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_inbox.py -v`
Expected: PASS (3 passed). Note: `read_inbox` collapses by id with last-write-wins, which is how `mark_triaged` updates status via append (jsonl stays append-only).

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/inbox.py tests/test_inbox.py
git commit -m "feat: append-only inbox.jsonl store with dedup + status

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 8: `add` — inbox-first capture with conditional write-through

**Files:**
- Create: `src/portfolio/add.py`, `tests/test_add.py`

**Interfaces:**
- Consumes: `inbox.*`, `init.init_repo`, `manifest.append_backlog_item`, `detect.is_git`.
- Produces: `infer_repo(cwd: Path, roots: list[Path]) -> tuple[Path | None, float]`; `tree_clean(repo: Path) -> bool`; `add_item(text, *, repo=None, priority=None, cwd, session=None, roots=None, today=None, now_iso=None) -> InboxItem`. Always appends to inbox; write-throughs to `PROJECT.md` (init-ing if absent) **only** when a repo is unambiguous, is git, and the tree is clean.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from pathlib import Path
from portfolio.add import add_item, infer_repo
from portfolio.manifest import read_manifest

def test_explicit_repo_clean_tree_writes_through(make_repo, portfolio_env):
    repo = make_repo("contacts", files={"package.json": '{"version":"1.0.0"}'})
    item = add_item("add carddav", repo=repo, cwd=repo, session="s1",
                    today=date(2026,6,25), now_iso="2026-06-25T10:00:00")
    assert item.status == "triaged"
    assert "add carddav" in read_manifest(repo).body   # wrote through
    assert read_manifest(repo) is not None              # init created it

def test_ambiguous_capture_stays_in_inbox(tmp_path, portfolio_env):
    # cwd not inside any root → cannot infer repo
    item = add_item("vague idea", cwd=tmp_path, roots=[tmp_path / "nope"],
                    session="s1", today=date(2026,6,25), now_iso="2026-06-25T10:00:00")
    assert item.status == "untriaged"
    assert item.inferred_repo is None

def test_dirty_tree_does_not_write_through(make_repo, portfolio_env):
    repo = make_repo("contacts")
    (repo / "dirty.txt").write_text("x")   # untracked change → not clean
    item = add_item("later", repo=repo, cwd=repo, session="s1",
                    today=date(2026,6,25), now_iso="2026-06-25T10:00:00")
    assert item.status == "untriaged"
    assert read_manifest(repo) is None     # never touched the manifest
```

- [ ] **Step 2: Run test, verify fails**

Run: `pytest tests/test_add.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/portfolio/add.py`**

```python
import subprocess
from datetime import date
from pathlib import Path

from . import config
from .detect import is_git
from .init import init_repo
from .inbox import InboxItem, append_inbox, new_id
from .manifest import append_backlog_item

def infer_repo(cwd: Path, roots: list[Path]) -> tuple[Path | None, float]:
    cwd = cwd.resolve()
    for root in roots:
        root = root.resolve()
        if cwd == root or root in cwd.parents:
            # the project dir is the immediate child of a root
            rel = cwd.relative_to(root)
            if rel.parts:
                return root / rel.parts[0], 0.9
    return None, 0.0

def tree_clean(repo: Path) -> bool:
    if not is_git(repo):
        return False
    out = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                         capture_output=True, text=True, timeout=5)
    return out.returncode == 0 and out.stdout.strip() == ""

def add_item(text, *, repo=None, priority=None, cwd, session=None,
             roots=None, today=None, now_iso) -> InboxItem:
    today = today or date.today()
    roots = roots or config.DEFAULT_ROOTS
    confidence = 1.0 if repo else 0.0
    if repo is None:
        repo, confidence = infer_repo(Path(cwd), roots)

    can_write = repo is not None and is_git(repo) and tree_clean(repo)
    item = InboxItem(id=new_id(text, now_iso), ts=now_iso, text=text,
                     inferred_repo=str(repo) if repo else None, confidence=confidence,
                     source_session=session, priority=priority,
                     status="triaged" if can_write else "untriaged")
    append_inbox(item)
    if can_write:
        init_repo(repo, today=today)
        append_backlog_item(repo, text, priority, today.isoformat())
    return item
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_add.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/add.py tests/test_add.py
git commit -m "feat: inbox-first capture with conditional write-through

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 9: `triage` + aggregate (records, json, digest)

**Files:**
- Create: `src/portfolio/triage.py`, `src/portfolio/aggregate.py`
- Create: `tests/test_triage.py`, `tests/test_aggregate.py`

**Interfaces:**
- triage produces: `untriaged() -> list[InboxItem]`; `assign(item_id: str, repo: Path, today: date | None = None) -> None` (init + append_backlog_item + mark_triaged).
- aggregate produces: `ProjectRecord` dataclass (`name, path, tier, status, version, version_source, purpose, updated, open_backlog, aged_backlog, git, findings, head_date, stale`); `build_records(roots: list[Path], today=None) -> list[ProjectRecord]`; `to_json(records, untriaged_count: int) -> str`; `render_digest(records, untriaged_count: int) -> str`. `build_records` also computes manifest **stale-vs-HEAD** here (the deferred check from Task 5) using `git log -1 --format=%cs`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_triage.py
from datetime import date
from portfolio.triage import untriaged, assign
from portfolio.inbox import InboxItem, append_inbox, new_id, read_inbox
from portfolio.manifest import read_manifest

def test_assign_writes_into_repo_and_marks_triaged(make_repo, portfolio_env):
    it = InboxItem(id=new_id("x","t"), ts="t", text="do x", inferred_repo=None,
                   confidence=0.0, source_session=None, priority="P2", status="untriaged")
    append_inbox(it)
    repo = make_repo("target")
    assign(it.id, repo, today=date(2026,6,25))
    assert "do x" in read_manifest(repo).body
    assert all(i.status == "triaged" for i in read_inbox() if i.id == it.id)
```

```python
# tests/test_aggregate.py
from datetime import date
from portfolio.aggregate import build_records, to_json, render_digest
import json

def test_build_records_counts_open_backlog(make_repo):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\n"
            "version_source: package.json\npurpose: p\nupdated: 2026-06-25\n---\n\n"
            "## Backlog\n- [ ] (P1) a — added 2026-06-01\n- [ ] (P2) b — added 2026-06-02\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    records = build_records([repo.parent], today=date(2026,6,26))
    rec = next(r for r in records if r.name == "x")
    assert rec.open_backlog == 2
    assert rec.tier == "active"

def test_to_json_and_digest_render(make_repo):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\n"
            "version_source: package.json\npurpose: does x\nupdated: 2026-06-25\n---\n\n## Backlog\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    records = build_records([repo.parent], today=date(2026,6,26))
    data = json.loads(to_json(records, untriaged_count=3))
    assert data["untriaged_count"] == 3
    assert data["projects"][0]["name"] == "x"
    digest = render_digest(records, untriaged_count=3)
    assert "| x " in digest and "Untriaged inbox items: 3" in digest
```

- [ ] **Step 2: Run tests, verify fail**

Run: `pytest tests/test_triage.py tests/test_aggregate.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/portfolio/triage.py`**

```python
from datetime import date
from pathlib import Path

from .inbox import InboxItem, read_inbox, mark_triaged
from .init import init_repo
from .manifest import append_backlog_item

def untriaged() -> list[InboxItem]:
    return [i for i in read_inbox() if i.status == "untriaged"]

def assign(item_id: str, repo: Path, today: date | None = None) -> None:
    today = today or date.today()
    item = next((i for i in read_inbox() if i.id == item_id), None)
    if item is None:
        raise KeyError(item_id)
    init_repo(repo, today=today)
    append_backlog_item(repo, item.text, item.priority, today.isoformat())
    mark_triaged(item_id)
```

- [ ] **Step 4: Implement `src/portfolio/aggregate.py`**

```python
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
    aged_backlog: int
    git: bool
    head_date: str | None
    stale: bool
    findings: list[dict]

def _head_date(repo: Path) -> str | None:
    if not is_git(repo):
        return None
    out = subprocess.run(["git", "log", "-1", "--format=%cs"], cwd=repo,
                         capture_output=True, text=True, timeout=5)
    return out.stdout.strip() or None if out.returncode == 0 else None

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
        fm = m.frontmatter if m else {}
        items = parse_backlog(m.body) if m else []
        open_count = sum(1 for i in items if not i.malformed)
        aged = sum(1 for f in lint(repo, today=today) if f.code == "aged_item")
        head = _head_date(repo)
        stale = False
        if head and fm.get("updated"):
            try:
                gap = (datetime.strptime(head, "%Y-%m-%d").date()
                       - datetime.strptime(str(fm["updated"]), "%Y-%m-%d").date()).days
                stale = gap > config.STALE_DAYS
            except ValueError:
                stale = False
        records.append(ProjectRecord(
            name=fm.get("name", repo.name), path=str(repo), tier=fm.get("tier"),
            status=fm.get("status"), version=fm.get("version"),
            version_source=fm.get("version_source"), purpose=fm.get("purpose"),
            updated=str(fm.get("updated")) if fm.get("updated") else None,
            open_backlog=open_count, aged_backlog=aged, git=is_git(repo),
            head_date=head, stale=stale,
            findings=[{"severity": f.severity, "code": f.code, "message": f.message}
                      for f in lint(repo, today=today)],
        ))
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
```

- [ ] **Step 5: Run tests, verify pass**

Run: `pytest tests/test_triage.py tests/test_aggregate.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/portfolio/triage.py src/portfolio/aggregate.py tests/test_triage.py tests/test_aggregate.py
git commit -m "feat: triage + aggregate (records, portfolio.json, digest, stale-vs-HEAD)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 10: `scan` + `query`

**Files:**
- Create: `src/portfolio/scan.py`, `src/portfolio/query.py`
- Create: `tests/test_scan.py`, `tests/test_query.py`

**Interfaces:**
- scan produces: `scan(roots=None, today=None) -> dict` — writes `portfolio.json` + `PORTFOLIO.md` to `config.portfolio_home()`, returns `{"projects": int, "fails": int, "warns": int}`.
- query produces: `query(filters: dict, json_text: str | None = None) -> list[dict]` — filters `portfolio.json` projects by `tier/status/tag/stale/has_backlog`. (`tag` matches a substring of purpose for now; tags-from-frontmatter is a Phase-2 extension.)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scan.py
from datetime import date
from portfolio.scan import scan
from portfolio import config
import json

def test_scan_writes_artifacts(make_repo, portfolio_env):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\n"
            "version_source: package.json\npurpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    summary = scan(roots=[repo.parent], today=date(2026,6,26))
    assert summary["projects"] == 1
    assert config.json_path().exists() and config.digest_path().exists()
    assert json.loads(config.json_path().read_text())["projects"][0]["name"] == "x"
```

```python
# tests/test_query.py
from portfolio.query import query

DATA = '{"untriaged_count":0,"projects":[' \
       '{"name":"a","tier":"active","status":"active","stale":false,"open_backlog":2,"purpose":"react app"},' \
       '{"name":"b","tier":"parking","status":"idea","stale":true,"open_backlog":0,"purpose":"shell script"}]}'

def test_query_filters_by_tier():
    rows = query({"tier": "active"}, json_text=DATA)
    assert [r["name"] for r in rows] == ["a"]

def test_query_filters_by_stale_and_status():
    assert [r["name"] for r in query({"stale": True}, json_text=DATA)] == ["b"]
    assert [r["name"] for r in query({"status": "active"}, json_text=DATA)] == ["a"]
```

- [ ] **Step 2: Run tests, verify fail**

Run: `pytest tests/test_scan.py tests/test_query.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/portfolio/scan.py`**

```python
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
```

- [ ] **Step 4: Implement `src/portfolio/query.py`**

```python
import json
from . import config

def query(filters: dict, json_text: str | None = None) -> list[dict]:
    data = json.loads(json_text) if json_text is not None else json.loads(config.json_path().read_text())
    rows = data.get("projects", [])
    def keep(p):
        if "tier" in filters and p.get("tier") != filters["tier"]:
            return False
        if "status" in filters and p.get("status") != filters["status"]:
            return False
        if "stale" in filters and bool(p.get("stale")) != bool(filters["stale"]):
            return False
        if "has_backlog" in filters and (p.get("open_backlog", 0) > 0) != bool(filters["has_backlog"]):
            return False
        if "tag" in filters and filters["tag"].lower() not in (p.get("purpose") or "").lower():
            return False
        return True
    return [p for p in rows if keep(p)]
```

- [ ] **Step 5: Run tests, verify pass**

Run: `pytest tests/test_scan.py tests/test_query.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/portfolio/scan.py src/portfolio/query.py tests/test_scan.py tests/test_query.py
git commit -m "feat: scan (writes json+digest) and query (filter portfolio.json)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 11: CLI dispatch

**Files:**
- Create: `src/portfolio/cli.py`, `src/portfolio/__main__.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: all command modules.
- Produces: `main(argv: list[str] | None = None) -> int`. Subcommands: `init <repo> [--tier]`, `lint <repo>`, `add <text> [--repo] [--priority]`, `triage` (lists untriaged; `--assign ID --repo R`), `scan [--roots ...]`, `query [--tier --status --stale --has-backlog --tag]`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from portfolio.cli import main
from portfolio import config

def test_cli_scan_runs_and_writes(make_repo, portfolio_env, capsys):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\n"
            "version_source: package.json\npurpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    rc = main(["scan", "--roots", str(repo.parent)])
    assert rc == 0
    assert config.json_path().exists()
    assert "projects" in capsys.readouterr().out

def test_cli_lint_returns_nonzero_on_fail(make_repo, portfolio_env):
    repo = make_repo("x")   # no PROJECT.md → FAIL
    assert main(["lint", str(repo)]) == 1
```

- [ ] **Step 2: Run test, verify fails**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `src/portfolio/cli.py` and `__main__.py`**

```python
# src/portfolio/__main__.py
from .cli import main
raise SystemExit(main())
```

```python
# src/portfolio/cli.py
import argparse
import json
from datetime import datetime
from pathlib import Path

from . import config
from .init import init_repo
from .validator import lint
from .add import add_item
from .triage import untriaged, assign
from .scan import scan
from .query import query

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="portfolio")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init"); p_init.add_argument("repo"); p_init.add_argument("--tier", default="active")
    p_lint = sub.add_parser("lint"); p_lint.add_argument("repo")
    p_add = sub.add_parser("add"); p_add.add_argument("text"); p_add.add_argument("--repo"); p_add.add_argument("--priority")
    p_tri = sub.add_parser("triage"); p_tri.add_argument("--assign"); p_tri.add_argument("--repo")
    p_scan = sub.add_parser("scan"); p_scan.add_argument("--roots", nargs="*")
    p_q = sub.add_parser("query")
    for flag in ("tier", "status", "tag"): p_q.add_argument(f"--{flag}")
    p_q.add_argument("--stale", action="store_true"); p_q.add_argument("--has-backlog", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "init":
        m = init_repo(Path(args.repo), tier=args.tier)
        print(f"initialized {m.path}"); return 0
    if args.cmd == "lint":
        findings = lint(Path(args.repo))
        for f in findings: print(f"{f.severity} {f.code}: {f.message}")
        return 1 if any(f.severity == "FAIL" for f in findings) else 0
    if args.cmd == "add":
        repo = Path(args.repo) if args.repo else None
        item = add_item(args.text, repo=repo, priority=args.priority, cwd=Path.cwd(),
                        now_iso=datetime.now().isoformat(timespec="seconds"))
        print(f"captured [{item.status}] {item.id}: {item.text}"); return 0
    if args.cmd == "triage":
        if args.assign and args.repo:
            assign(args.assign, Path(args.repo)); print(f"assigned {args.assign}"); return 0
        for i in untriaged(): print(f"{i.id}  conf={i.confidence}  {i.text}")
        return 0
    if args.cmd == "scan":
        roots = [Path(r) for r in args.roots] if args.roots else None
        print(json.dumps(scan(roots=roots))); return 0
    if args.cmd == "query":
        filters = {k: v for k, v in (("tier", args.tier), ("status", args.status), ("tag", args.tag)) if v}
        if args.stale: filters["stale"] = True
        if args.has_backlog: filters["has_backlog"] = True
        for p in query(filters): print(f"{p['name']:24} {p.get('tier','-'):8} {p.get('status','-')}")
        return 0
    return 2
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full suite + a real smoke test**

Run: `pytest -q`
Expected: PASS (all). Then smoke:
```bash
PYTHONPATH=src python3 -m portfolio init /tmp/smoke-repo 2>/dev/null || (mkdir -p /tmp/smoke-repo && PYTHONPATH=src python3 -m portfolio init /tmp/smoke-repo)
PYTHONPATH=src python3 -m portfolio lint /tmp/smoke-repo
```
Expected: prints `initialized …/PROJECT.md` then lint output (a `not_git` FAIL is expected for the bare /tmp dir).

- [ ] **Step 6: Commit**

```bash
git add src/portfolio/cli.py src/portfolio/__main__.py tests/test_cli.py
git commit -m "feat: argparse CLI dispatch for all subcommands

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 12: Integrations — skill, hook, LaunchAgent, standard doc

**Files:**
- Create: `integrations/backlog.skill.md`, `integrations/portfolio-nudge.sh`, `integrations/com.devon.portfolio-scan.plist`, `integrations/install.sh`, `README.md`

**Interfaces:**
- Consumes: the `portfolio` CLI via `PYTHONPATH`.
- Produces: installable artifacts. No Python; this task is bash + markdown + a plist.

- [ ] **Step 1: Write `integrations/backlog.skill.md`** (the capture skill)

````markdown
---
name: backlog
description: Use when Devon says "put that on the backlog", "/backlog", "add to the backlog", or wants to record a future work item discovered mid-session. Captures the item via the portfolio CLI so it lands consistently (inbox-first, write-through to the repo's PROJECT.md when unambiguous).
---

# Backlog capture

When invoked, capture each item the user named by running, once per item:

```bash
PYTHONPATH="$HOME/Projects/project-standards/src" python3 -m portfolio add "<item text>" --priority <P1|P2|P3|omit>
```

Rules:
- Run from the repo's working directory so `add` can infer the project. If the user named a different project, pass `--repo "$HOME/Projects/<name>"`.
- Capture verbatim intent; do not editorialize. One `add` per distinct item.
- After capturing, tell the user where each item landed (the command prints `[triaged]` = written to PROJECT.md, or `[untriaged]` = held in inbox for `portfolio triage`).
- Never hand-edit PROJECT.md for backlog items — always go through `portfolio add` so the format stays consistent.
````

- [ ] **Step 2: Write `integrations/portfolio-nudge.sh`** (Stop hook)

```bash
#!/usr/bin/env bash
# Non-blocking Stop hook: warn (never block) if the session's repo lacks/has a stale PROJECT.md.
set -euo pipefail
REPO="$(git rev-parse --show-toplevel 2>/dev/null || true)"
[ -z "$REPO" ] && exit 0
OUT="$(PYTHONPATH="$HOME/Projects/project-standards/src" python3 -m portfolio lint "$REPO" 2>/dev/null || true)"
if echo "$OUT" | grep -q "FAIL missing_manifest"; then
  echo "💡 portfolio: this repo has no PROJECT.md — run 'portfolio init .' to add one." >&2
elif echo "$OUT" | grep -q "FAIL"; then
  echo "💡 portfolio: PROJECT.md has issues:" >&2
  echo "$OUT" | grep "FAIL" >&2
fi
exit 0   # always non-blocking
```

- [ ] **Step 3: Write `integrations/com.devon.portfolio-scan.plist`** (weekly, mirrors security-scan)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.devon.portfolio-scan</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string><string>-lc</string>
    <string>PYTHONPATH="$HOME/Projects/project-standards/src" python3 -m portfolio scan</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/tmp/portfolio-scan.log</string>
  <key>StandardErrorPath</key><string>/tmp/portfolio-scan.err</string>
</dict></plist>
```

- [ ] **Step 4: Write `integrations/install.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.claude/skills/backlog"
cp "$HERE/backlog.skill.md" "$HOME/.claude/skills/backlog/SKILL.md"
install -m 0755 "$HERE/portfolio-nudge.sh" "$HOME/.claude/hooks/portfolio-nudge.sh"
cp "$HERE/com.devon.portfolio-scan.plist" "$HOME/Library/LaunchAgents/com.devon.portfolio-scan.plist"
launchctl unload "$HOME/Library/LaunchAgents/com.devon.portfolio-scan.plist" 2>/dev/null || true
launchctl load "$HOME/Library/LaunchAgents/com.devon.portfolio-scan.plist"
echo "Installed backlog skill, nudge hook, and weekly portfolio-scan LaunchAgent."
echo "NOTE: register portfolio-nudge.sh as a Stop hook in ~/.claude/settings.json manually."
```

- [ ] **Step 5: Write `README.md`** (the standard — abbreviated; full schema table required)

````markdown
# project-standards

The portfolio standard: every project carries a repo-root `PROJECT.md` (source of truth for
its dev-state + backlog). The `portfolio` CLI scaffolds, validates, captures, and aggregates.

## PROJECT.md schema
Frontmatter (active tier requires all; parking requires name/tier/status/purpose):

| field | values |
|-------|--------|
| name | string |
| tier | active \| parking |
| status | idea \| in-progress \| active \| archived |
| version | string \| n/a |
| version_source | package.json \| pyproject \| cargo \| git-tag \| none |
| purpose | one line |
| updated | YYYY-MM-DD |
| links | optional map (specs, roadmap) |

Body: `## Backlog` (checkbox lines `- [ ] (P#) text — added YYYY-MM-DD`) + `## Future plans`.

## CLI
`PYTHONPATH="$HOME/Projects/project-standards/src" python3 -m portfolio <cmd>` —
`init <repo>`, `lint <repo>`, `add "<text>"`, `triage`, `scan`, `query`.

## Install integrations
`bash integrations/install.sh`
````

- [ ] **Step 6: Lint the bash + validate the plist**

Run:
```bash
bash -n integrations/portfolio-nudge.sh && bash -n integrations/install.sh && echo "bash OK"
plutil -lint integrations/com.devon.portfolio-scan.plist
```
Expected: `bash OK` and `OK` from plutil.

- [ ] **Step 7: Commit**

```bash
git add integrations README.md
git commit -m "feat: integrations (backlog skill, nudge hook, scan LaunchAgent) + standard doc

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 13: End-to-end verification + rollout dry-run

**Files:**
- Create: `tests/test_e2e.py`

**Interfaces:** none new — exercises the full capture → triage → scan → query loop.

- [ ] **Step 1: Write the e2e test**

```python
from datetime import date
from pathlib import Path
from portfolio.add import add_item
from portfolio.triage import untriaged, assign
from portfolio.scan import scan
from portfolio.query import query
from portfolio import config
import json

def test_capture_triage_scan_query_loop(make_repo, portfolio_env, tmp_path):
    repo = make_repo("contacts", files={"package.json": '{"version":"1.0.0"}'})
    # ambiguous capture (cwd outside roots) → inbox
    item = add_item("cross-project idea", cwd=tmp_path, roots=[tmp_path / "none"],
                    session="s", today=date(2026,6,25), now_iso="2026-06-25T10:00:00")
    assert item.status == "untriaged" and len(untriaged()) == 1
    # triage into the repo
    assign(item.id, repo, today=date(2026,6,25))
    assert untriaged() == []
    # scan + query
    scan(roots=[repo.parent], today=date(2026,6,26))
    data = json.loads(config.json_path().read_text())
    assert data["untriaged_count"] == 0
    actives = query({"tier": "active"})
    assert any(p["name"] == "contacts" for p in actives)
```

- [ ] **Step 2: Run the full suite**

Run: `pytest -q`
Expected: PASS (all tests, ~28+).

- [ ] **Step 3: Real-world dry-run (read-only) against the actual portfolio**

Run (does NOT write to repos; only scans + writes ~/.portfolio):
```bash
PYTHONPATH=src PORTFOLIO_HOME=/tmp/portfolio-dryrun python3 -m portfolio scan
cat /tmp/portfolio-dryrun/PORTFOLIO.md | head -40
```
Expected: a digest table listing the real projects, with `not_git`/`missing_manifest` FAILs for the projects that lack `PROJECT.md` (the pre-rollout state). This proves the scanner reads the real layout before any migration.

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: end-to-end capture/triage/scan/query loop + dry-run verified

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

## Rollout (after the toolkit is built — operational, not code)

1. **Active set first (non-blocking):** for each of the ~23 active projects, run `portfolio init <repo>`, then hand-write the one-line `purpose` (pull from App Brain where it exists). Commit each `PROJECT.md` in its own repo.
2. **Tier-triage the long tail:** run `portfolio init <repo> --tier parking` for scratch dirs; they need only name/status/purpose. Non-git dirs stay flagged — do NOT auto-`git init`.
3. **Install integrations:** `bash integrations/install.sh`, then register the Stop hook in `~/.claude/settings.json`.
4. **First real scan:** `portfolio scan`; read `~/.portfolio/PORTFOLIO.md`. Drift (un-migrated repos) shows as FAILs — that's the worklist, not an error.

## Out of scope (separate plans)
- **Phase 2:** Watchtower consuming `portfolio.json` (different repo; its own plan).
- **Phase 3:** App Brain ⇄ purpose sync; optional `gh issue create` mirror.
