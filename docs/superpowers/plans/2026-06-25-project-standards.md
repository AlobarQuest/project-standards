# Project Standards (portfolio toolkit) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `portfolio` CLI + `backlog` capture skill + weekly scanner that make a repo-local `PROJECT.md` the single source of truth for project state/backlog across ~52 repos, with capture that always succeeds via a central inbox.

**Architecture:** A zero-install Python package (`src/` layout, run via `PYTHONPATH=… python3 -m portfolio.cli`, exactly like `security-standards`). A pure validator is the shared core, consumed by `init`, `add`, `triage`, `scan`, and a session hook. Capture writes to `~/.portfolio/inbox.jsonl` first and write-throughs to `PROJECT.md` only when the repo is unambiguous and the tree is clean. Derived views (`portfolio.json`, `PORTFOLIO.md`) are regenerated, never committed.

**Tech Stack:** Python 3.12 (stdlib `tomllib`, `json`, `subprocess`, `dataclasses`, `pathlib`, `hashlib`, `datetime`), PyYAML for frontmatter, pytest for tests. Bash for the LaunchAgent wrapper + Stop hook. No network deps.

> **Revision note (2026-06-25):** This plan was stress-tested in a 2nd multi-LLM debate (Codex + Copilot, both BUILD-WITH-CHANGES). Eleven fixes were folded in and are called out inline with **[debate-fix]**: YAML-error guard, transactional capture, flexible dash regex, malformed-JSONL isolation, stale-as-finding, repo validation, CLI `nargs`/triage-guard, `install.sh` mkdir, Task 9 split, plus robustness tests (Task 14). Transcript: `~/.claude-octopus/debates/session/002-project-standards-plan/`.

## Global Constraints

- Python **3.12+** (stdlib `tomllib`). One third-party runtime dep only: **PyYAML**.
- Invocation: `PYTHONPATH="$HOME/Projects/project-standards/src" python3 -m portfolio.cli <subcommand>`.
- Source of truth is the repo's `PROJECT.md`. The CLI **never runs `git init`** and **never rewrites or reorders existing `## Backlog` lines** (append-only).
- Derived artifacts live in `~/.portfolio/` (`inbox.jsonl`, `portfolio.json`, `PORTFOLIO.md`) and are **never committed**.
- Manifest filename is exactly `PROJECT.md` at repo root.
- `tier ∈ {active, parking}`; `status ∈ {idea, in-progress, active, archived}`; `version_source ∈ {package.json, pyproject, cargo, git-tag, none}`.
- Required frontmatter — active: `name, tier, status, version, version_source, purpose, updated`; parking: `name, tier, status, purpose`.
- Thresholds: manifest "stale" if `updated` is **> 30 days** behind git HEAD date; backlog item "aged" if `added` is **> 180 days** old.
- **No tool call may crash on bad input.** Malformed YAML, malformed JSONL, missing commits, and dash variants must degrade to a finding or a skip — never an exception out of the CLI.
- TDD throughout. Commit messages end with the two CLAUDE.md trailers. Tests must not touch the real `~/.portfolio` or real repos — use `tmp_path` + the `PORTFOLIO_HOME` env override.

---

## File Structure

```
project-standards/
  pyproject.toml
  src/portfolio/
    __init__.py  __main__.py
    config.py        # paths (PORTFOLIO_HOME override), default roots, thresholds
    schema.py        # constants + Finding + validate_frontmatter() (pure)
    manifest.py      # parse/render PROJECT.md (YAML-guarded), parse_backlog (dash-tolerant), append_backlog_item
    detect.py        # name/version/remote/is_git/purpose
    validator.py     # lint(repo) -> list[Finding]  (shared core; bad_yaml aware)
    init.py          # init_repo() idempotent scaffold/repair
    inbox.py         # InboxItem + jsonl read(malformed-isolated)/append/mark_triaged + new_id
    add.py           # add_item() transactional inbox-first capture
    triage.py        # untriaged()/assign()
    aggregate.py     # ProjectRecord, build_records (stale-as-finding), to_json, render_digest
    scan.py          # scan(roots) -> writes json + digest
    query.py         # query(filters) over portfolio.json
    cli.py           # argparse dispatch
  tests/
    conftest.py + one test_*.py per module + test_e2e.py + test_robustness.py
  integrations/
    backlog.skill.md  portfolio-nudge.sh  com.devon.portfolio-scan.plist  install.sh
  README.md
```

`validator.py` is the only module that composes the others; `cli.py` is thin dispatch.

---

### Task 1: Package scaffold + config

**Files:** Create `pyproject.toml`, `src/portfolio/__init__.py`, `src/portfolio/config.py`, `tests/conftest.py`, `tests/test_config.py`

**Interfaces — Produces:** `config.portfolio_home() -> Path`; `config.inbox_path()/json_path()/digest_path() -> Path`; `config.DEFAULT_ROOTS: list[Path]`; `config.STALE_DAYS=30`; `config.BACKLOG_AGE_DAYS=180`.

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

- [ ] **Step 2: Write the failing test** `tests/test_config.py`

```python
from pathlib import Path
from portfolio import config

def test_portfolio_home_defaults(monkeypatch):
    monkeypatch.delenv("PORTFOLIO_HOME", raising=False)
    assert config.portfolio_home() == Path.home() / ".portfolio"

def test_portfolio_home_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PORTFOLIO_HOME", str(tmp_path))
    assert config.portfolio_home() == tmp_path
    assert config.inbox_path() == tmp_path / "inbox.jsonl"
```

- [ ] **Step 3: Run, verify fail** — `pytest tests/test_config.py -v` → FAIL `ModuleNotFoundError`

- [ ] **Step 4: Implement `__init__.py` (empty) + `config.py`**

```python
import os
from pathlib import Path

DEFAULT_ROOTS = [Path.home() / "Projects", Path.home() / "Developer"]
STALE_DAYS = 30
BACKLOG_AGE_DAYS = 180

def portfolio_home() -> Path:
    override = os.environ.get("PORTFOLIO_HOME")
    return Path(override) if override else Path.home() / ".portfolio"

def inbox_path() -> Path:  return portfolio_home() / "inbox.jsonl"
def json_path() -> Path:   return portfolio_home() / "portfolio.json"
def digest_path() -> Path: return portfolio_home() / "PORTFOLIO.md"
```

- [ ] **Step 5: Write `tests/conftest.py` shared fixtures**

```python
import subprocess
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
    def _make(name, git=True, files=None, commit=True):
        repo = tmp_path / name
        repo.mkdir()
        for rel, content in (files or {}).items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        if git:
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            if commit:
                subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
                subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                                "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
        return repo
    return _make
```

- [ ] **Step 6: Run, verify pass** — `pytest tests/test_config.py -v` → PASS (2)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/portfolio tests
git commit -m "feat: package scaffold + config (paths, roots, thresholds)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 2: Schema + pure frontmatter validator

**Files:** Create `src/portfolio/schema.py`, `tests/test_schema.py`

**Interfaces — Produces:** `Finding(severity, code, message)` dataclass (`severity ∈ {"FAIL","WARN"}`); `validate_frontmatter(fm: dict) -> list[Finding]`; constants `TIERS, STATUSES, VERSION_SOURCES, REQUIRED_ACTIVE, REQUIRED_PARKING`.

- [ ] **Step 1: Write the failing test**

```python
from portfolio.schema import validate_frontmatter

def _active(**over):
    fm = {"name": "x", "tier": "active", "status": "active", "version": "1.0.0",
          "version_source": "package.json", "purpose": "does x", "updated": "2026-06-25"}
    fm.update(over); return fm

def test_valid_active_has_no_findings():
    assert validate_frontmatter(_active()) == []

def test_missing_required_active_field_is_fail():
    fm = _active(); del fm["updated"]
    assert any(f.code == "missing_field" and "updated" in f.message and f.severity == "FAIL"
               for f in validate_frontmatter(fm))

def test_parking_does_not_require_version():
    assert validate_frontmatter({"name": "x", "tier": "parking", "status": "idea", "purpose": "x"}) == []

def test_bad_enum_is_fail():
    assert any(f.code == "bad_enum" and f.severity == "FAIL"
               for f in validate_frontmatter({"name": "x", "tier": "parking", "status": "bogus", "purpose": "x"}))
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_schema.py -v` → FAIL

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
        required = REQUIRED_PARKING
    else:
        required = REQUIRED_ACTIVE if tier == "active" else REQUIRED_PARKING
    for field in required:
        if not fm.get(field):
            findings.append(Finding("FAIL", "missing_field", f"missing required field: {field}"))
    if fm.get("status") and fm["status"] not in STATUSES:
        findings.append(Finding("FAIL", "bad_enum", f"status invalid: {fm['status']!r}"))
    if fm.get("version_source") and fm["version_source"] not in VERSION_SOURCES:
        findings.append(Finding("FAIL", "bad_enum", f"version_source invalid: {fm['version_source']!r}"))
    return findings
```

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_schema.py -v` → PASS (4)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/schema.py tests/test_schema.py
git commit -m "feat: PROJECT.md frontmatter schema + pure validator

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 3: Manifest read/render + dash-tolerant append-only backlog

**Files:** Create `src/portfolio/manifest.py`, `tests/test_manifest.py`

**Interfaces — Produces:** `Manifest(frontmatter, body, path)`; `read_manifest(repo) -> Manifest | None`; `write_manifest(m)`; `parse_frontmatter(text) -> tuple[dict, str]` (**[debate-fix]** YAML-error-guarded: on bad YAML returns `({"_yaml_error": msg}, body)`); `parse_backlog(body) -> list[BacklogItem]` (`BacklogItem(text, priority, added, raw, malformed)`, **[debate-fix]** accepts `—`/`–`/`-`/`--` separators); `append_backlog_item(repo, text, priority, added)` (append-only, writes canonical `—`).

- [ ] **Step 1: Write the failing test**

```python
from portfolio.manifest import (read_manifest, write_manifest, parse_backlog,
                                append_backlog_item, parse_frontmatter)

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

def test_round_trip_preserves_fields(tmp_path):
    (tmp_path / "PROJECT.md").write_text(MANIFEST)
    m = read_manifest(tmp_path)
    assert m.frontmatter["name"] == "demo" and "Future plans" in m.body
    write_manifest(m)
    assert read_manifest(tmp_path).frontmatter["version"] == "1.2.0"

def test_parse_backlog_extracts_priority_and_date(tmp_path):
    (tmp_path / "PROJECT.md").write_text(MANIFEST)
    items = parse_backlog(read_manifest(tmp_path).body)
    assert items[0].priority == "P2" and items[0].added == "2026-05-01" and items[0].malformed is False

def test_parse_backlog_accepts_dash_variants():
    # en-dash, ASCII hyphen, double-hyphen all parse, not just em-dash  [debate-fix]
    body = ("## Backlog\n"
            "- [ ] (P1) en dash – added 2026-01-01\n"
            "- [ ] (P2) ascii hyphen - added 2026-02-02\n"
            "- [ ] (P3) double -- added 2026-03-03\n")
    items = parse_backlog(body)
    assert [i.added for i in items] == ["2026-01-01", "2026-02-02", "2026-03-03"]
    assert all(not i.malformed for i in items)

def test_completed_items_parse_not_malformed():
    items = parse_backlog("## Backlog\n- [x] (P2) done thing — added 2026-01-01\n")
    assert items[0].malformed is False and items[0].text == "done thing"

def test_append_is_additive_and_preserves_lines(tmp_path):
    (tmp_path / "PROJECT.md").write_text(MANIFEST)
    append_backlog_item(tmp_path, "new thing", "P1", "2026-06-25")
    body = (tmp_path / "PROJECT.md").read_text()
    assert "existing item" in body and "## Future plans" in body
    assert "(P1) new thing — added 2026-06-25" in body

def test_append_when_no_backlog_section(tmp_path):
    (tmp_path / "PROJECT.md").write_text("---\nname: x\ntier: parking\nstatus: idea\npurpose: p\n---\n\nbody\n")
    append_backlog_item(tmp_path, "first", None, "2026-06-25")
    assert "## Backlog" in (tmp_path / "PROJECT.md").read_text()
    assert "first — added 2026-06-25" in (tmp_path / "PROJECT.md").read_text()

def test_parse_frontmatter_bad_yaml_does_not_raise():
    fm, _ = parse_frontmatter("---\nname: x\n  bad: : :\n---\nbody\n")
    assert "_yaml_error" in fm

def test_read_missing_returns_none(tmp_path):
    assert read_manifest(tmp_path) is None
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_manifest.py -v` → FAIL

- [ ] **Step 3: Implement `src/portfolio/manifest.py`**

```python
import re
from dataclasses import dataclass
from pathlib import Path
import yaml

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
# [debate-fix] tolerate em/en/ascii/double dash as the "added" separator
BACKLOG_LINE_RE = re.compile(
    r"^- \[[ xX]\] (?:\((?P<priority>P\d)\) )?(?P<text>.*?)"
    r"(?:\s+[—–-]{1,2}\s+added\s+(?P<added>\d{4}-\d{2}-\d{2}))?\s*$"
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
    try:                                              # [debate-fix]
        fm = yaml.safe_load(match.group(1)) or {}
        if not isinstance(fm, dict):
            return {"_yaml_error": "frontmatter is not a mapping"}, match.group(2)
    except yaml.YAMLError as e:
        return {"_yaml_error": str(e)}, match.group(2)
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
    items, in_section = [], False
    for line in body.splitlines():
        if line.strip().lower() == "## backlog":
            in_section = True; continue
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
    new_line = f"- [ ] {prefix}{text} — added {added}"     # canonical em-dash
    lines, out, inserted = content.splitlines(), [], False
    for i, line in enumerate(lines):
        out.append(line)
        if not inserted and line.strip().lower() == "## backlog":
            j = i + 1
            while j < len(lines) and (lines[j].strip().startswith("- [") or not lines[j].strip()):
                out.append(lines[j]); j += 1
            out.append(new_line); inserted = True
            out.extend(lines[j:]); break
    if not inserted:
        out += ["", "## Backlog", new_line]
    path.write_text("\n".join(out) + ("\n" if content.endswith("\n") else ""))
```

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_manifest.py -v` → PASS (8)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/manifest.py tests/test_manifest.py
git commit -m "feat: manifest parse/render (YAML-guarded) + dash-tolerant append-only backlog

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 4: Detection (name/version/remote/git/purpose)

**Files:** Create `src/portfolio/detect.py`, `tests/test_detect.py`

**Interfaces — Produces:** `detect_name(repo) -> str`; `detect_version(repo) -> tuple[str, str]` (`(version, source)`, source ∈ VERSION_SOURCES); `is_git(repo) -> bool`; `detect_remote(repo) -> str | None`; `detect_purpose(repo) -> str | None`. All git calls are exception-safe (return None/default, never raise).

- [ ] **Step 1: Write the failing test**

```python
from portfolio.detect import detect_name, detect_version, is_git, detect_purpose

def test_version_from_package_json(make_repo):
    assert detect_version(make_repo("p", files={"package.json": '{"version": "3.4.5"}'})) == ("3.4.5", "package.json")

def test_version_from_pyproject(make_repo):
    assert detect_version(make_repo("p", files={"pyproject.toml": '[project]\nversion = "2.0.1"\n'})) == ("2.0.1", "pyproject")

def test_version_none_when_undetectable(make_repo):
    assert detect_version(make_repo("p", files={"README.md": "hi"})) == ("n/a", "none")

def test_version_survives_malformed_package_json(make_repo):
    assert detect_version(make_repo("p", files={"package.json": "{not json"})) == ("n/a", "none")

def test_name_is_dir_name(make_repo):
    assert detect_name(make_repo("contacts")) == "contacts"

def test_is_git_true_false(make_repo):
    assert is_git(make_repo("g", git=True)) is True
    assert is_git(make_repo("ng", git=False)) is False

def test_purpose_from_readme_first_prose_line(make_repo):
    assert detect_purpose(make_repo("p", files={"README.md": "# Title\n\nDoes the thing well.\n"})) == "Does the thing well."
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_detect.py -v` → FAIL

- [ ] **Step 3: Implement `src/portfolio/detect.py`**

```python
import json
import subprocess
import tomllib
from pathlib import Path

def detect_name(repo: Path) -> str:
    return repo.name

def is_git(repo: Path) -> bool:
    return (repo / ".git").exists()   # True for both .git dir and worktree .git file

def detect_version(repo: Path) -> tuple[str, str]:
    pkg = repo / "package.json"
    if pkg.exists():
        try:
            v = json.loads(pkg.read_text()).get("version")
            if v: return str(v), "package.json"
        except (json.JSONDecodeError, OSError): pass
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
            v = data.get("project", {}).get("version") or data.get("tool", {}).get("poetry", {}).get("version")
            if v: return str(v), "pyproject"
        except (tomllib.TOMLDecodeError, OSError): pass
    cargo = repo / "Cargo.toml"
    if cargo.exists():
        try:
            v = tomllib.loads(cargo.read_text()).get("package", {}).get("version")
            if v: return str(v), "cargo"
        except (tomllib.TOMLDecodeError, OSError): pass
    if is_git(repo):
        tag = _git(repo, ["describe", "--tags", "--abbrev=0"])
        if tag: return tag, "git-tag"
    return "n/a", "none"

def detect_remote(repo: Path) -> str | None:
    return _git(repo, ["remote", "get-url", "origin"]) or None if is_git(repo) else None

def detect_purpose(repo: Path) -> str | None:
    readme = repo / "README.md"
    if not readme.exists(): return None
    for line in readme.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith(("#", "!", "[")):
            return s
    return None

def _git(repo: Path, args: list[str]) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else None
    except (subprocess.SubprocessError, OSError):
        return None
```

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_detect.py -v` → PASS (7)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/detect.py tests/test_detect.py
git commit -m "feat: exception-safe project metadata detection

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 5: Validator (the shared core)

**Files:** Create `src/portfolio/validator.py`, `tests/test_validator.py`

**Interfaces — Consumes:** `schema.validate_frontmatter`, `manifest.read_manifest/parse_backlog`, `detect.is_git`, `config.BACKLOG_AGE_DAYS`. **Produces:** `lint(repo, today=None) -> list[Finding]`. Empty ⇒ OK. **[debate-fix]** emits `bad_yaml` FAIL when frontmatter has `_yaml_error`. (Stale-vs-HEAD is NOT here — it needs a git-date lookup and is surfaced in Task 10's aggregate as a `stale_manifest` finding; `lint` stays git-date-free so the Stop hook hot path is cheap.)

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from portfolio.validator import lint

def _good_active():
    return ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\n"
            "version_source: package.json\npurpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n")

def test_missing_manifest_is_fail(make_repo):
    assert any(f.code == "missing_manifest" and f.severity == "FAIL" for f in lint(make_repo("x")))

def test_conforming_active_repo_is_clean(make_repo):
    repo = make_repo("x", files={"PROJECT.md": _good_active(), "package.json": '{"version":"1.0.0"}'})
    assert lint(repo, today=date(2026, 6, 26)) == []

def test_bad_yaml_is_fail(make_repo):
    repo = make_repo("x", files={"PROJECT.md": "---\nname: x\n bad: : :\n---\n"})
    assert any(f.code == "bad_yaml" and f.severity == "FAIL" for f in lint(repo, today=date(2026,6,26)))

def test_non_git_active_is_fail(make_repo):
    repo = make_repo("x", git=False, files={"PROJECT.md": _good_active().replace("1.0.0","n/a").replace("package.json","none")})
    assert any(f.code == "not_git" and f.severity == "FAIL" for f in lint(repo, today=date(2026,6,26)))

def test_aged_backlog_item_is_warn(make_repo):
    body = _good_active().replace("## Backlog\n", "## Backlog\n- [ ] (P3) old — added 2025-01-01\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    assert any(f.code == "aged_item" and f.severity == "WARN" for f in lint(repo, today=date(2026,6,26)))
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_validator.py -v` → FAIL

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
    if "_yaml_error" in m.frontmatter:                      # [debate-fix]
        return [Finding("FAIL", "bad_yaml", f"{repo.name}: invalid frontmatter: {m.frontmatter['_yaml_error']}")]
    findings = list(validate_frontmatter(m.frontmatter))
    tier = m.frontmatter.get("tier")
    if not is_git(repo):
        findings.append(Finding("FAIL" if tier == "active" else "WARN", "not_git", f"{repo.name}: not a git repo"))
    for item in parse_backlog(m.body):
        if item.malformed:
            findings.append(Finding("WARN", "malformed_item", f"{repo.name}: malformed backlog line: {item.raw.strip()}"))
        elif item.added:
            try:
                if (today - datetime.strptime(item.added, "%Y-%m-%d").date()).days > config.BACKLOG_AGE_DAYS:
                    findings.append(Finding("WARN", "aged_item", f"{repo.name}: aged backlog item: {item.text}"))
            except ValueError:
                findings.append(Finding("WARN", "malformed_item", f"{repo.name}: bad date: {item.raw.strip()}"))
    return findings
```

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_validator.py -v` → PASS (5)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/validator.py tests/test_validator.py
git commit -m "feat: validator core (bad_yaml/missing/not_git/backlog findings)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 6: `init` — idempotent scaffold/repair

**Files:** Create `src/portfolio/init.py`, `tests/test_init.py`

**Interfaces — Consumes:** `detect.*`, `manifest.Manifest/read_manifest/write_manifest`. **Produces:** `init_repo(repo, tier="active", today=None) -> Manifest`. Idempotent (fills only blanks), never overwrites human values, never runs `git init`, preserves body.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from portfolio.init import init_repo
from portfolio.manifest import read_manifest

def test_init_creates_conforming_manifest(make_repo):
    repo = make_repo("contacts", files={"package.json": '{"version":"0.4.2"}', "README.md": "# Contacts\n\nContact hub.\n"})
    init_repo(repo, today=date(2026, 6, 25))
    fm = read_manifest(repo).frontmatter
    assert fm["name"] == "contacts" and fm["version"] == "0.4.2" and fm["version_source"] == "package.json"
    assert fm["purpose"] == "Contact hub." and fm["updated"] == "2026-06-25" and fm["tier"] == "active"

def test_init_does_not_clobber_human_fields(make_repo):
    body = ("---\nname: contacts\ntier: active\nstatus: active\nversion: 9.9.9\nversion_source: package.json\n"
            "purpose: HAND WRITTEN\nupdated: 2026-01-01\n---\n\n## Backlog\n- [ ] (P1) keep me — added 2026-01-01\n")
    repo = make_repo("contacts", files={"PROJECT.md": body, "package.json": '{"version":"0.4.2"}'})
    init_repo(repo, today=date(2026, 6, 25))
    m = read_manifest(repo)
    assert m.frontmatter["purpose"] == "HAND WRITTEN" and m.frontmatter["version"] == "9.9.9" and "keep me" in m.body

def test_init_never_creates_git(make_repo):
    repo = make_repo("scratch", git=False)
    init_repo(repo, tier="parking", today=date(2026, 6, 25))
    assert not (repo / ".git").exists()
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_init.py -v` → FAIL

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
    fm = dict(existing.frontmatter) if existing and "_yaml_error" not in existing.frontmatter else {}
    body = existing.body if existing else (ACTIVE_BODY if tier == "active" else PARKING_BODY)

    fm.setdefault("name", detect.detect_name(repo))
    fm.setdefault("tier", tier)
    fm.setdefault("status", "in-progress")
    fm.setdefault("purpose", detect.detect_purpose(repo) or "TODO: one-line purpose")
    if fm.get("tier") == "active":
        if not fm.get("version"):
            fm["version"], fm["version_source"] = detect.detect_version(repo)
        fm.setdefault("version_source", "none")
        fm.setdefault("updated", today.isoformat())

    m = Manifest(frontmatter=fm, body=body, path=repo / "PROJECT.md")
    write_manifest(m)
    return m
```

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_init.py -v` → PASS (3)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/init.py tests/test_init.py
git commit -m "feat: idempotent init (no clobber, no git init)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 7: Inbox store (malformed-line isolated)

**Files:** Create `src/portfolio/inbox.py`, `tests/test_inbox.py`

**Interfaces — Produces:** `InboxItem(id, ts, text, inferred_repo, confidence, source_session, priority, status)`; `new_id(text, ts) -> str`; `append_inbox(item)`; `read_inbox() -> list[InboxItem]` (**[debate-fix]** skips malformed JSON lines); `mark_triaged(item_id)`; `find_duplicate(text) -> InboxItem | None`.

- [ ] **Step 1: Write the failing test**

```python
from portfolio.inbox import InboxItem, append_inbox, read_inbox, mark_triaged, new_id, find_duplicate
from portfolio import config

def _item(text="do x"):
    return InboxItem(id=new_id(text, "2026-06-25T10:00:00.000000"), ts="2026-06-25T10:00:00.000000",
                     text=text, inferred_repo=None, confidence=0.0, source_session="s1",
                     priority=None, status="untriaged")

def test_append_and_read_roundtrip(portfolio_env):
    append_inbox(_item("alpha")); append_inbox(_item("beta"))
    assert [i.text for i in read_inbox()] == ["alpha", "beta"]

def test_mark_triaged_updates_status(portfolio_env):
    it = _item("gamma"); append_inbox(it); mark_triaged(it.id)
    assert read_inbox()[0].status == "triaged"

def test_malformed_line_is_skipped(portfolio_env):
    append_inbox(_item("good"))
    with config.inbox_path().open("a") as f:
        f.write("{ this is not valid json\n")
    assert [i.text for i in read_inbox()] == ["good"]   # bad line ignored, no crash

def test_find_duplicate(portfolio_env):
    append_inbox(_item("same text"))
    assert find_duplicate("same text") is not None and find_duplicate("different") is None
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_inbox.py -v` → FAIL

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
        if not line.strip():
            continue
        try:                                       # [debate-fix] isolate bad lines
            d = json.loads(line)
            items[d["id"]] = InboxItem(**d)        # later status updates win
        except (json.JSONDecodeError, TypeError, KeyError):
            continue
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

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_inbox.py -v` → PASS (4)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/inbox.py tests/test_inbox.py
git commit -m "feat: inbox.jsonl store with malformed-line isolation + dedup

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 8: `add` — transactional inbox-first capture

**Files:** Create `src/portfolio/add.py`, `tests/test_add.py`

**Interfaces — Consumes:** `inbox.*`, `init.init_repo`, `manifest.append_backlog_item`, `detect.is_git`. **Produces:** `infer_repo(cwd, roots) -> tuple[Path | None, float]`; `tree_clean(repo) -> bool` (exception-safe); `add_item(text, *, repo=None, priority=None, cwd, session=None, roots=None, today=None, now_iso) -> InboxItem`.

**[debate-fix] Transactional + validated:** always append the item **untriaged** first; only if the repo is valid (exists, is a dir, is git, clean tree) attempt write-through under `try/except`; append a **triaged** status update *only after* the manifest write succeeds. A write-through failure leaves the item safely untriaged (never "triaged but lost").

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from portfolio.add import add_item, infer_repo
from portfolio.manifest import read_manifest

NOW = "2026-06-25T10:00:00.000000"

def test_explicit_repo_clean_tree_writes_through(make_repo, portfolio_env):
    repo = make_repo("contacts", files={"package.json": '{"version":"1.0.0"}'})
    item = add_item("add carddav", repo=repo, cwd=repo, session="s1", today=date(2026,6,25), now_iso=NOW)
    assert item.status == "triaged" and "add carddav" in read_manifest(repo).body

def test_ambiguous_capture_stays_in_inbox(tmp_path, portfolio_env):
    item = add_item("vague idea", cwd=tmp_path, roots=[tmp_path / "nope"], session="s1",
                    today=date(2026,6,25), now_iso=NOW)
    assert item.status == "untriaged" and item.inferred_repo is None

def test_dirty_tree_does_not_write_through(make_repo, portfolio_env):
    repo = make_repo("contacts")
    (repo / "dirty.txt").write_text("x")
    item = add_item("later", repo=repo, cwd=repo, session="s1", today=date(2026,6,25), now_iso=NOW)
    assert item.status == "untriaged" and read_manifest(repo) is None

def test_nonexistent_repo_does_not_crash(tmp_path, portfolio_env):
    item = add_item("x", repo=tmp_path / "missing", cwd=tmp_path, session="s",
                    today=date(2026,6,25), now_iso=NOW)
    assert item.status == "untriaged"   # invalid repo → inbox only, no exception
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_add.py -v` → FAIL

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
    cwd = Path(cwd).resolve()
    for root in roots:
        root = Path(root).resolve()
        if cwd == root or root in cwd.parents:
            rel = cwd.relative_to(root)
            if rel.parts:
                return root / rel.parts[0], 0.9
    return None, 0.0

def tree_clean(repo: Path) -> bool:
    if not is_git(repo):
        return False
    try:
        out = subprocess.run(["git", "status", "--porcelain"], cwd=repo,
                             capture_output=True, text=True, timeout=5)
        return out.returncode == 0 and out.stdout.strip() == ""
    except (subprocess.SubprocessError, OSError):
        return False

def _valid_repo(repo) -> Path | None:
    if repo is None:
        return None
    repo = Path(repo)
    return repo if repo.exists() and repo.is_dir() else None

def add_item(text, *, repo=None, priority=None, cwd, session=None,
             roots=None, today=None, now_iso) -> InboxItem:
    today = today or date.today()
    roots = roots or config.DEFAULT_ROOTS
    repo = _valid_repo(repo)
    confidence = 1.0 if repo else 0.0
    if repo is None:
        repo, confidence = infer_repo(cwd, roots)

    can_write = repo is not None and is_git(repo) and tree_clean(repo)
    item = InboxItem(id=new_id(text, now_iso), ts=now_iso, text=text,
                     inferred_repo=str(repo) if repo else None, confidence=confidence,
                     source_session=session, priority=priority, status="untriaged")
    append_inbox(item)                                  # [debate-fix] untriaged first
    if can_write:
        try:
            init_repo(repo, today=today)
            append_backlog_item(repo, text, priority, today.isoformat())
        except (OSError, ValueError):
            return item                                 # leave untriaged on failure
        item.status = "triaged"
        append_inbox(item)                              # status update only after success
    return item
```

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_add.py -v` → PASS (4)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/add.py tests/test_add.py
git commit -m "feat: transactional inbox-first capture (validated repo, fail-safe)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 9: `triage`

**Files:** Create `src/portfolio/triage.py`, `tests/test_triage.py`

**Interfaces — Consumes:** `inbox.read_inbox/mark_triaged`, `init.init_repo`, `manifest.append_backlog_item`. **Produces:** `untriaged() -> list[InboxItem]`; `assign(item_id, repo, today=None) -> None` (init + append + mark_triaged; raises `KeyError` for unknown id).

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from portfolio.triage import untriaged, assign
from portfolio.inbox import InboxItem, append_inbox, new_id, read_inbox
from portfolio.manifest import read_manifest
import pytest

def _untriaged(text="do x"):
    return InboxItem(id=new_id(text,"t"), ts="t", text=text, inferred_repo=None,
                     confidence=0.0, source_session=None, priority="P2", status="untriaged")

def test_assign_writes_into_repo_and_marks_triaged(make_repo, portfolio_env):
    it = _untriaged(); append_inbox(it)
    repo = make_repo("target")
    assign(it.id, repo, today=date(2026,6,25))
    assert "do x" in read_manifest(repo).body
    assert all(i.status == "triaged" for i in read_inbox() if i.id == it.id)
    assert untriaged() == []

def test_assign_unknown_id_raises(portfolio_env, make_repo):
    with pytest.raises(KeyError):
        assign("nope", make_repo("r"))
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_triage.py -v` → FAIL

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

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_triage.py -v` → PASS (2)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/triage.py tests/test_triage.py
git commit -m "feat: triage (assign inbox items into PROJECT.md)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 10: Aggregate (records, json, digest, stale-as-finding)

**Files:** Create `src/portfolio/aggregate.py`, `tests/test_aggregate.py`

**Interfaces — Consumes:** `manifest.read_manifest/parse_backlog`, `detect.is_git`, `validator.lint`, `config.STALE_DAYS`. **Produces:** `ProjectRecord` (`name, path, tier, status, version, version_source, purpose, updated, open_backlog, git, head_date, stale, findings`); `build_records(roots, today=None) -> list[ProjectRecord]`; `to_json(records, untriaged_count) -> str`; `render_digest(records, untriaged_count) -> str`. **[debate-fix]** computes stale-vs-HEAD via `git log -1 --format=%cs` and appends a `stale_manifest` WARN to `findings` so `scan` counts it.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from portfolio.aggregate import build_records, to_json, render_digest
import json

def _manifest(updated="2026-06-25"):
    return (f"---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: package.json\n"
            f"purpose: does x\nupdated: {updated}\n---\n\n## Backlog\n- [ ] (P1) a — added 2026-06-01\n- [ ] (P2) b — added 2026-06-02\n")

def test_build_records_counts_open_backlog(make_repo):
    repo = make_repo("x", files={"PROJECT.md": _manifest()})
    rec = next(r for r in build_records([repo.parent], today=date(2026,6,26)) if r.name == "x")
    assert rec.open_backlog == 2 and rec.tier == "active"

def test_to_json_and_digest(make_repo):
    repo = make_repo("x", files={"PROJECT.md": _manifest()})
    records = build_records([repo.parent], today=date(2026,6,26))
    data = json.loads(to_json(records, untriaged_count=3))
    assert data["untriaged_count"] == 3 and data["projects"][0]["name"] == "x"
    digest = render_digest(records, untriaged_count=3)
    assert "| x " in digest and "Untriaged inbox items: 3" in digest

def test_stale_manifest_becomes_finding(make_repo):
    # manifest updated long before HEAD commit (make_repo commits at "now") → stale
    repo = make_repo("x", files={"PROJECT.md": _manifest(updated="2025-01-01")})
    rec = next(r for r in build_records([repo.parent], today=date(2026,6,26)) if r.name == "x")
    assert rec.stale is True
    assert any(f["code"] == "stale_manifest" and f["severity"] == "WARN" for f in rec.findings)
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_aggregate.py -v` → FAIL

> **Note for the implementer:** `test_stale_manifest_becomes_finding` relies on `make_repo` committing at wall-clock time (so HEAD date ≈ today, manifest `updated` = 2025-01-01, gap > 30d). This is the one test whose HEAD date isn't injected; it's robust because the gap is ~18 months, far exceeding `STALE_DAYS`.

- [ ] **Step 3: Implement `src/portfolio/aggregate.py`**

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
```

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_aggregate.py -v` → PASS (3)

- [ ] **Step 5: Commit**

```bash
git add src/portfolio/aggregate.py tests/test_aggregate.py
git commit -m "feat: aggregate (records, json, digest, stale-as-finding)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 11: `scan` + `query`

**Files:** Create `src/portfolio/scan.py`, `src/portfolio/query.py`, `tests/test_scan.py`, `tests/test_query.py`

**Interfaces — Produces:** `scan(roots=None, today=None) -> dict` (writes `portfolio.json` + `PORTFOLIO.md`, returns `{"projects","fails","warns"}`); `query(filters: dict, json_text: str | None = None) -> list[dict]` (filters by `tier/status/tag/stale/has_backlog`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scan.py
from datetime import date
from portfolio.scan import scan
from portfolio import config
import json

def test_scan_writes_artifacts(make_repo, portfolio_env):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: package.json\n"
            "purpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n")
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
    assert [r["name"] for r in query({"tier": "active"}, json_text=DATA)] == ["a"]

def test_query_filters_by_stale_and_status():
    assert [r["name"] for r in query({"stale": True}, json_text=DATA)] == ["b"]
    assert [r["name"] for r in query({"status": "active"}, json_text=DATA)] == ["a"]
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_scan.py tests/test_query.py -v` → FAIL

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
    def keep(p):
        if "tier" in filters and p.get("tier") != filters["tier"]: return False
        if "status" in filters and p.get("status") != filters["status"]: return False
        if "stale" in filters and bool(p.get("stale")) != bool(filters["stale"]): return False
        if "has_backlog" in filters and (p.get("open_backlog", 0) > 0) != bool(filters["has_backlog"]): return False
        if "tag" in filters and filters["tag"].lower() not in (p.get("purpose") or "").lower(): return False
        return True
    return [p for p in data.get("projects", []) if keep(p)]
```

- [ ] **Step 5: Run, verify pass** — `pytest tests/test_scan.py tests/test_query.py -v` → PASS (3)

- [ ] **Step 6: Commit**

```bash
git add src/portfolio/scan.py src/portfolio/query.py tests/test_scan.py tests/test_query.py
git commit -m "feat: scan (writes json+digest) + query (filter portfolio.json)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 12: CLI dispatch

**Files:** Create `src/portfolio/cli.py`, `src/portfolio/__main__.py`, `tests/test_cli.py`

**Interfaces — Produces:** `main(argv=None) -> int`. Subcommands: `init <repo> [--tier]`, `lint <repo>`, `add <text...> [--repo] [--priority]` (**[debate-fix]** `nargs="+"`), `triage [--assign ID --repo R]` (**[debate-fix]** `--assign` without `--repo` errors), `scan [--roots ...]`, `query [--tier --status --stale --has-backlog --tag]`. Capture timestamps use **microsecond** precision (**[debate-fix]** reduces id collisions).

- [ ] **Step 1: Write the failing test**

```python
from portfolio.cli import main
from portfolio import config

def test_cli_scan_runs_and_writes(make_repo, portfolio_env, capsys):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\nversion_source: package.json\n"
            "purpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    assert main(["scan", "--roots", str(repo.parent)]) == 0
    assert config.json_path().exists() and "projects" in capsys.readouterr().out

def test_cli_lint_nonzero_on_fail(make_repo, portfolio_env):
    assert main(["lint", str(make_repo("x"))]) == 1     # no PROJECT.md → FAIL

def test_cli_add_accepts_multiword(make_repo, portfolio_env):
    repo = make_repo("contacts", files={"package.json": '{"version":"1.0.0"}'})
    import os; os.chdir(repo)
    assert main(["add", "fix", "the", "login", "flow", "--repo", str(repo)]) == 0

def test_cli_triage_assign_without_repo_errors(portfolio_env):
    assert main(["triage", "--assign", "abc"]) == 2
```

- [ ] **Step 2: Run, verify fail** — `pytest tests/test_cli.py -v` → FAIL

- [ ] **Step 3: Implement `__main__.py` + `cli.py`**

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

from .init import init_repo
from .validator import lint
from .add import add_item
from .triage import untriaged, assign
from .scan import scan
from .query import query

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="portfolio")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("repo"); p.add_argument("--tier", default="active")
    p = sub.add_parser("lint"); p.add_argument("repo")
    p = sub.add_parser("add"); p.add_argument("text", nargs="+"); p.add_argument("--repo"); p.add_argument("--priority")
    p = sub.add_parser("triage"); p.add_argument("--assign"); p.add_argument("--repo")
    p = sub.add_parser("scan"); p.add_argument("--roots", nargs="*")
    p = sub.add_parser("query")
    for flag in ("tier", "status", "tag"): p.add_argument(f"--{flag}")
    p.add_argument("--stale", action="store_true"); p.add_argument("--has-backlog", action="store_true")
    args = parser.parse_args(argv)

    if args.cmd == "init":
        print(f"initialized {init_repo(Path(args.repo), tier=args.tier).path}"); return 0
    if args.cmd == "lint":
        findings = lint(Path(args.repo))
        for f in findings: print(f"{f.severity} {f.code}: {f.message}")
        return 1 if any(f.severity == "FAIL" for f in findings) else 0
    if args.cmd == "add":
        item = add_item(" ".join(args.text), repo=Path(args.repo) if args.repo else None,
                        priority=args.priority, cwd=Path.cwd(),
                        now_iso=datetime.now().isoformat(timespec="microseconds"))
        print(f"captured [{item.status}] {item.id}: {item.text}"); return 0
    if args.cmd == "triage":
        if args.assign:
            if not args.repo:
                print("error: --assign requires --repo"); return 2     # [debate-fix]
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
        for x in query(filters): print(f"{x['name']:24} {x.get('tier','-'):8} {x.get('status','-')}")
        return 0
    return 2
```

- [ ] **Step 4: Run, verify pass** — `pytest tests/test_cli.py -v` → PASS (4)

- [ ] **Step 5: Full suite + smoke**

Run: `pytest -q` → PASS (all). Then:
```bash
mkdir -p /tmp/smoke-repo && PYTHONPATH=src python3 -m portfolio init /tmp/smoke-repo
PYTHONPATH=src python3 -m portfolio lint /tmp/smoke-repo
```
Expected: `initialized …/PROJECT.md`, then a `not_git` FAIL for the bare dir.

- [ ] **Step 6: Commit**

```bash
git add src/portfolio/cli.py src/portfolio/__main__.py tests/test_cli.py
git commit -m "feat: argparse CLI (multiword add, triage --repo guard, microsecond ids)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 13: Integrations — skill, hook, LaunchAgent, standard doc

**Files:** Create `integrations/backlog.skill.md`, `integrations/portfolio-nudge.sh`, `integrations/com.devon.portfolio-scan.plist`, `integrations/install.sh`, `README.md`

- [ ] **Step 1: Write `integrations/backlog.skill.md`**

````markdown
---
name: backlog
description: Use when Devon says "put that on the backlog", "/backlog", "add to the backlog", or wants to record a future work item discovered mid-session. Captures via the portfolio CLI so it lands consistently (inbox-first, write-through to the repo's PROJECT.md when unambiguous).
---

# Backlog capture

For each item the user named, run once (from the repo's working directory so the project is inferred):

```bash
PYTHONPATH="$HOME/Projects/project-standards/src" python3 -m portfolio add "<item text>" --priority <P1|P2|P3|omit>
```

Rules:
- If the user named a different project, pass `--repo "$HOME/Projects/<name>"`.
- Capture verbatim intent; one `add` per distinct item; do not editorialize.
- Report where each landed: `[triaged]` = written to PROJECT.md, `[untriaged]` = held in inbox for `portfolio triage`.
- Never hand-edit PROJECT.md for backlog items — always go through `portfolio add`.
````

- [ ] **Step 2: Write `integrations/portfolio-nudge.sh`** (Stop hook — wording matches what `lint` checks)

```bash
#!/usr/bin/env bash
# Non-blocking Stop hook: warn (never block) if the session's repo has a missing
# or invalid PROJECT.md. (Staleness is reported by the weekly scan, not here.)
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
exit 0
```

- [ ] **Step 3: Write `integrations/com.devon.portfolio-scan.plist`**

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

- [ ] **Step 4: Write `integrations/install.sh`** (**[debate-fix]** creates the hooks dir)

```bash
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.claude/skills/backlog" "$HOME/.claude/hooks" "$HOME/Library/LaunchAgents"
cp "$HERE/backlog.skill.md" "$HOME/.claude/skills/backlog/SKILL.md"
install -m 0755 "$HERE/portfolio-nudge.sh" "$HOME/.claude/hooks/portfolio-nudge.sh"
cp "$HERE/com.devon.portfolio-scan.plist" "$HOME/Library/LaunchAgents/com.devon.portfolio-scan.plist"
launchctl unload "$HOME/Library/LaunchAgents/com.devon.portfolio-scan.plist" 2>/dev/null || true
launchctl load "$HOME/Library/LaunchAgents/com.devon.portfolio-scan.plist"
echo "Installed backlog skill, nudge hook, and weekly portfolio-scan LaunchAgent."
echo "NOTE: register portfolio-nudge.sh as a Stop hook in ~/.claude/settings.json manually."
```

- [ ] **Step 5: Write `README.md`** (the standard)

````markdown
# project-standards

Every project carries a repo-root `PROJECT.md` (source of truth for its dev-state + backlog).
The `portfolio` CLI scaffolds, validates, captures, and aggregates.

## PROJECT.md schema
Frontmatter (active requires all; parking requires name/tier/status/purpose):

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

Body: `## Backlog` (lines `- [ ] (P#) text — added YYYY-MM-DD`) + `## Future plans`.

## CLI
`PYTHONPATH="$HOME/Projects/project-standards/src" python3 -m portfolio <cmd>` —
`init <repo>`, `lint <repo>`, `add "<text>"`, `triage`, `scan`, `query`.

## Install integrations
`bash integrations/install.sh` (then register the Stop hook in `~/.claude/settings.json`).
````

- [ ] **Step 6: Lint bash + validate plist**

Run:
```bash
bash -n integrations/portfolio-nudge.sh && bash -n integrations/install.sh && echo "bash OK"
plutil -lint integrations/com.devon.portfolio-scan.plist
```
Expected: `bash OK` and `OK`.

- [ ] **Step 7: Commit**

```bash
git add integrations README.md
git commit -m "feat: integrations (backlog skill, nudge hook, scan LaunchAgent) + standard doc

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

### Task 14: End-to-end + robustness tests

**Files:** Create `tests/test_e2e.py`, `tests/test_robustness.py`

**[debate-fix]** The robustness suite covers the production failure modes both reviewers flagged: malformed YAML, repos with no commits, `PROJECT.md` with no `## Backlog`, completed items, and a malformed inbox line — all must degrade gracefully, never crash a scan.

- [ ] **Step 1: Write `tests/test_e2e.py`**

```python
from datetime import date
from portfolio.add import add_item
from portfolio.triage import untriaged, assign
from portfolio.scan import scan
from portfolio.query import query
from portfolio import config
import json

def test_capture_triage_scan_query_loop(make_repo, portfolio_env, tmp_path):
    repo = make_repo("contacts", files={"package.json": '{"version":"1.0.0"}'})
    item = add_item("cross-project idea", cwd=tmp_path, roots=[tmp_path / "none"],
                    session="s", today=date(2026,6,25), now_iso="2026-06-25T10:00:00.000000")
    assert item.status == "untriaged" and len(untriaged()) == 1
    assign(item.id, repo, today=date(2026,6,25))
    assert untriaged() == []
    scan(roots=[repo.parent], today=date(2026,6,26))
    assert json.loads(config.json_path().read_text())["untriaged_count"] == 0
    assert any(p["name"] == "contacts" for p in query({"tier": "active"}))
```

- [ ] **Step 2: Write `tests/test_robustness.py`**

```python
from datetime import date
from portfolio.scan import scan
from portfolio.aggregate import build_records

def test_scan_survives_malformed_yaml(make_repo, portfolio_env):
    make_repo("bad", files={"PROJECT.md": "---\nname: x\n bad: : :\n---\n"})
    summary = scan(roots=[(make_repo("bad2").parent)], today=date(2026,6,26))  # same tmp parent
    assert summary["projects"] >= 1   # did not raise

def test_no_commit_repo_does_not_crash(make_repo):
    repo = make_repo("fresh", git=True, commit=False)   # git init, zero commits
    recs = build_records([repo.parent], today=date(2026,6,26))
    rec = next(r for r in recs if r.name == "fresh")
    assert rec.head_date is None and rec.stale is False   # no HEAD → not stale, no crash

def test_manifest_without_backlog_section(make_repo, portfolio_env):
    body = "---\nname: x\ntier: parking\nstatus: idea\npurpose: p\n---\n\njust prose\n"
    repo = make_repo("x", files={"PROJECT.md": body})
    rec = next(r for r in build_records([repo.parent], today=date(2026,6,26)) if r.name == "x")
    assert rec.open_backlog == 0   # no section → zero, not error

def test_completed_items_counted(make_repo):
    body = ("---\nname: x\ntier: active\nstatus: active\nversion: n/a\nversion_source: none\n"
            "purpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n- [x] done — added 2026-06-01\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    rec = next(r for r in build_records([repo.parent], today=date(2026,6,26)) if r.name == "x")
    assert rec.open_backlog == 1   # parsed, not malformed
```

- [ ] **Step 3: Run the full suite**

Run: `pytest -q`
Expected: PASS (all, ~35+ tests).

- [ ] **Step 4: Read-only dry-run against the real portfolio**

Run (writes only to a throwaway home, never to repos):
```bash
PYTHONPATH=src PORTFOLIO_HOME=/tmp/portfolio-dryrun python3 -m portfolio scan
head -40 /tmp/portfolio-dryrun/PORTFOLIO.md
```
Expected: a digest listing the real projects, with `missing_manifest`/`not_git` FAILs for the pre-rollout state. Proves the scanner reads the real layout without touching it.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e.py tests/test_robustness.py
git commit -m "test: e2e loop + robustness (malformed yaml/no-commit/no-backlog/completed)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LYs3MmcnqmH4chKQ25bB6n"
```

---

## Rollout (operational, after the toolkit is built)

1. **Active set first (non-blocking):** for each of the ~23 active projects, `portfolio init <repo>`, hand-write the one-line `purpose` (pull from App Brain where it exists), commit each `PROJECT.md` in its own repo.
2. **Tier-triage the long tail:** `portfolio init <repo> --tier parking` for scratch dirs (name/status/purpose only). Non-git dirs stay flagged — never auto-`git init`.
3. **Install integrations:** `bash integrations/install.sh`, then register the Stop hook in `~/.claude/settings.json`.
4. **First real scan:** `portfolio scan`; read `~/.portfolio/PORTFOLIO.md`. Drift shows as FAILs — that's the worklist.

## Out of scope (separate plans)
- **Phase 2:** Watchtower consuming `portfolio.json` (different repo; its own plan).
- **Phase 3:** App Brain ⇄ purpose sync + divergence finding; optional `gh issue create` mirror; unhandled-mkdir-permission hardening (debate item #12, deferred).
