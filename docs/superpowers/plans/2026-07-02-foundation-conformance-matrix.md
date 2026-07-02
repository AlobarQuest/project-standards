# WS-0.0: Foundation Census + Conformance Matrix

## Context

The software-factory master plan (`~/docs/software-delivery-system/2026-07-02-software-factory-master-plan.md`) requires the foundational repos to provably comply with each other's standards before higher layers are built. Every standard already has a checker, but nothing runs all checkers against all foundational repos and shows one answer. This builds that instrument: a `portfolio foundation` command in `~/Projects/project-standards` producing a repo × standard conformance matrix, plus the census (frontmatter declarations) across the confirmed 9-repo roster. The matrix output becomes the authoritative Phase 0 worklist, and green-or-accepted is Phase 0's finish line.

**Roster (Devon-confirmed, core 9):** security-standards, code-standards, project-standards, infraops-mcp-server, brain, change-manager, vps-backup, alobar-id, provider-agent-pattern. (watchtower/ops-dashboard deferred to Phase 6.)

## Design

**New subcommand:** `PYTHONPATH=src python3 -m portfolio foundation [--roots ...]` — separate from `scan` (different cadence, subprocess-heavy, different exit-code contract).

**Standards / matrix columns:** per-repo `project`, `security`, `code`, `infra`; machine-scope `governance` (separate one-row section, participates in exit code).

**Cell values:** `pass` / `violation` / `accepted-exception` / `not-applicable` / `unknown`. Fail-closed: checker missing/timeout/garbled/stale → `unknown` with note, never silent pass. Exit codes: 0 = no violations, 1 = any violation, 2 = internal error (malformed exceptions file, zero foundational repos). Unknown cells exit 0 but render in a loud "work items" section.

**Census keys (PROJECT.md frontmatter, lint-tolerated today, validated after this change):**
- `foundation: true` (bool)
- `applicable_standards: [project, security, code, infra]` (⊆ known set)
- `coolify_resources: [name-or-uuid, ...]` (apps AND dbs; required when `infra` declared)

**Checker adapters** (new `src/portfolio/checkers.py`, shared `_run()` subprocess helper modeled on `detect._git`, default timeout 120s):
- `project`: internal — reuse `validator.lint(repo)`; FAIL → violation, WARN-only → pass (WARNs kept in details).
- `security`: `python3 -m security_scan.cli <repo> --category security` with `PYTHONPATH=<security-standards>/src`; JSON stdout; BLOCK>0 → violation. Per-repo `.security-scan-allow.toml` already applied underneath; judgment/WARN/NOTE findings stay in details on pass cells.
- `code`: **`.code-standards.toml` absent → synthetic violation `code.not-onboarded`** (guards code-standards' silent-pass on un-onboarded repos — the matrix's most important cell). Else `code-standards check --repo <repo>` (via `uv run` in `~/Developer/code-standards`; exact invocation verified at Task 7): exit 0 pass / 1 violation / 2 unknown.
- `governance` (machine): `python -m security_scan.governance verify` in security-standards; exit 1 → violation with problem lines. **Full verify, not `--artifacts-only`** — OWNERSHIP.md freshness flapping is real drift signal.
- `infra` + backup coverage: **consume, never invoke** — read freshest `<YYYY-MM-DD>.json` from `$INFRADRIFT_REPORT_DIR` (default `~/infra-drift/reports`, written nightly at 3AM; regex-match date-named files only, excluding `.remediation.json` siblings). `generated_at` older than 36h → unknown ("stale report"); any instance `ok: false` → unknown for all. Map proposals to repos by `target.uuid`/`target.name` ∈ `coolify_resources`. Backup gaps arrive as rule-572 proposals inside this report. No BWS/network needed by the matrix itself.

**Exceptions:** `foundation-exceptions.toml` at project-standards repo root (versioned). Entries: `repo, standard, finding` (fnmatch glob, e.g. `572:*` for hash-suffixed infra ids), `reason, added, revisit` — mirroring the ADR-0001 accepted-risk pattern. Malformed file → exit 2 (fail closed). Fully-matched violations → `accepted-exception`; matrix also reports **unused exceptions** (stale-exception hygiene). Governance exceptions use `repo = "_machine"`.

**Artifacts** (mirroring scan): `~/.portfolio/foundation.json` (full report incl. summary counts + exit_code) and `~/.portfolio/FOUNDATION.md` (matrix table with ✅/❌/⚠ accepted/—/?, then Violations / Accepted exceptions / Unknown / Stale exceptions sections).

**Config** (`config.py`, env-override functions matching `portfolio_home()` pattern): `security_standards_repo()` ($SECURITY_STANDARDS_REPO), `code_standards_repo()` ($CODE_STANDARDS_REPO), `infra_report_dir()` ($INFRADRIFT_REPORT_DIR — same var drift-audit.sh uses), `exceptions_path()`, `checker_timeout()`, `infra_max_age_hours()`, `foundation_json_path()`, `foundation_digest_path()`.

**Resolved design questions:** unknown→exit 0 in v1 (`--strict` deferred); first run accepts a red `code` column (that's the census's purpose — no pre-onboarding, no blanket exceptions); scheduling stays manual in v1 (weekly wiring happens at Phase 0 exit per master plan); `coolify_resources` (not `coolify_apps`) since proposals target DBs too.

## Files

- **Create:** `src/portfolio/{checkers,exceptions,matrix,foundation}.py`, `foundation-exceptions.toml` (seeded empty + header comment), `tests/{test_checkers,test_exceptions,test_matrix,test_foundation}.py`
- **Modify:** `src/portfolio/{cli,config,schema}.py`, `tests/{test_cli,test_schema,test_config}.py`, `README.md`, `PROJECT.md` (backlog entry + `Plan:` ref per convention)
- **Repo plan copy:** `docs/superpowers/plans/2026-07-02-foundation-conformance-matrix.md`
- **Census (data):** PROJECT.md frontmatter in the 9 roster repos

## Tasks (TDD; feature branch in project-standards; commit per task)

1. **Schema census keys** — validate `foundation` (bool), `applicable_standards` (⊆ {project,security,code,infra}), `coolify_resources` (list of str); WARN `foundation_incomplete` when `foundation: true` lacks `applicable_standards`; WARN when `infra` declared without `coolify_resources`. Unknown keys stay tolerated.
2. **Config additions** — path/timeout functions with env overrides; tests via monkeypatch.setenv.
3. **exceptions.py** — tomllib load + required-field validation (raise `ExceptionsError`) + `matches()` with fnmatch; tests incl. glob and fail-closed malformed file.
4. **matrix.py** — `CheckResult`/`Cell`/`Row` dataclasses, `resolve_cell()` (violation partition by exceptions, used-exception tracking), `summary()`, `to_report()` (json-able), `render_digest()`; tests for partition semantics, counts, markdown sections.
5. **check_project** — wraps `validator.lint`; tests with `make_repo` fixture.
6. **check_security** — subprocess adapter; tests monkeypatch `checkers._run` for BLOCK/clean/None/garbled; assert cmd+env construction.
7. **check_code** — not-onboarded guard first (test proves `_run` NOT called), then check invocation; verify real `uv run` entry against code-standards before finalizing; exit-code mapping tests.
8. **check_governance** — machine-scope adapter; pass/violation/unknown tests.
9. **check_infra** — batch adapter over the report file; tests with fake report dir + injected `now`: name and uuid matching, stale (40h), missing report, missing `coolify_resources`, `ok:false` instance, `.remediation.json` sibling ignored.
10. **foundation.py orchestrator + integration** — discovery via `aggregate._iter_repos` + `foundation: true` frontmatter; NA for undeclared standards; artifacts written; exit_code computed; `FoundationError` on empty roster; unused-exceptions reported. Integration test: stub security_scan module in tmp dir exercising the real subprocess path.
11. **CLI wiring** — `foundation` subparser; summary line print; exit codes 0/1/2 tested via `main([...])` + capsys.
12. **Seed + docs** — empty `foundation-exceptions.toml`, README section (usage, cell legend, exceptions workflow, env overrides), full pytest green, backlog entry with `Plan:` ref, copy plan into `docs/superpowers/plans/`.
13. **Census rollout (9 repos)** — hand-edit each PROJECT.md frontmatter (NOT via `write_manifest` — yaml re-wrap causes noisy diffs); `portfolio lint` each; manifest-only commit per repo (`chore: declare foundation membership in PROJECT.md`, staging only PROJECT.md — matches the earlier rollout pattern). Applicability: all 9 get `project, security`; `code` for all except provider-agent-pattern + alobar-id (confirm by content at rollout — pattern/compose-config repos may be NA); `infra` + `coolify_resources` for brain (4 apps + DBs) and change-manager (app + DB) — take exact names/uuids from the latest drift report / app-brain, not from `resource_name` parses.
14. **First real run + triage** — `python3 -m portfolio foundation`; expected reds: `code.not-onboarded` widely, brain security manifest (placeholder BWS UUIDs), possibly infra/backup cells. Triage each red: fix now / becomes a Phase-0 worklist item in that repo's PROJECT.md backlog / dated exception with revisit trigger. Commit exceptions + a snapshot of FOUNDATION.md findings into the master-plan doc directory as the WS-0.0 deliverable record.

## Verification

- `PYTHONPATH=src python3 -m pytest` green in project-standards.
- `PYTHONPATH=src python3 -m portfolio foundation` runs end-to-end against the real 9 repos: exits 1 (violations exist today — brain BWS placeholders, code onboarding gaps), `~/.portfolio/FOUNDATION.md` shows the expected reds and the correct NA/unknown cells, `foundation.json` parses and matches.
- Negative checks: temporarily corrupt `foundation-exceptions.toml` → exit 2; point `$INFRADRIFT_REPORT_DIR` at an empty dir → infra cells `unknown`, exit unaffected by unknowns.
- `portfolio lint` still passes on all 9 edited repos (census keys tolerated + validated).
- Re-run `portfolio foundation` twice — idempotent, same result.
- `/code-review` on the project-standards diff before declaring done (per code-quality convention).
