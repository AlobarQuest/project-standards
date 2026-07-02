# Project Standards

**A single, consistent way to track the state and backlog of every project in the
portfolio.** Each repo carries one file — `PROJECT.md` at its root — that is the source of
truth for what the project is, how active it is, and what work is still open. A small
zero-install toolkit scaffolds, validates, captures into, and rolls up those files across
all ~50 repos under `~/Projects` and `~/Developer`.

This document explains the standard, how it's enforced, and the tools. For day-to-day tool
usage see **[`integrations/README.md`](integrations/README.md)**; for the full design and
rationale see the [implementation plan](docs/superpowers/plans/2026-06-25-project-standards.md)
and [design spec](docs/superpowers/specs/2026-06-25-project-standards-design.md).

---

## Why this exists

Backlogs and project state used to be scattered — some in your head, some in Todoist, some
in README TODOs, some nowhere. Across dozens of repos that meant no single place to answer
"what projects do I have, which are active, and what's left to do on each?"

The fix is deliberately low-tech: **a committed `PROJECT.md` in each repo** is the one place
that state lives. Because it's committed, it travels with the repo and any agent or human
that opens the repo can read it. A weekly/daily scan aggregates every `PROJECT.md` into one
portfolio-wide view.

This repo standardizes **project state + backlog**. It is one of a family of standards
repos — see [Related standards](#related-standards) for the code-quality and security
siblings.

---

## How it works (the model)

```
  each repo/PROJECT.md   ──┐
  (source of truth,        │   portfolio scan      ~/.portfolio/PORTFOLIO.md   (the digest)
   committed, travels)     ├──────────────────▶    ~/.portfolio/portfolio.json (machine-readable)
                           │   (daily 03:00)        — derived, never committed
  capture (backlog skill / │
   portfolio add) ─▶ inbox ─┘
   ~/.portfolio/inbox.jsonl
```

- **Source of truth:** every project has a repo-root `PROJECT.md` (committed).
- **Two tiers:** `active` projects carry a full manifest; `parking` projects (long-tail,
  experiments, utilities) carry a minimal one.
- **Inbox-first capture:** new backlog items are captured to a central inbox first, then
  written through to the right repo's `PROJECT.md` when the target is unambiguous. Items
  that can't auto-place wait in the inbox for triage.
- **Derived views are regenerated, never committed:** the rollup (`portfolio.json` +
  `PORTFOLIO.md`) and the inbox live under `~/.portfolio/` and are rebuilt by each scan.

**Inbox vs backlog:** *inbox* = captured but not yet placed into a repo; *backlog* = items
that have landed in a repo's `PROJECT.md` and show up in the rollup.

---

## The `PROJECT.md` standard

### Frontmatter (YAML)

`active` tier requires all fields; `parking` requires only `name`, `tier`, `status`, `purpose`.

| field | values |
|-------|--------|
| `name` | string |
| `tier` | `active` \| `parking` |
| `status` | `idea` \| `in-progress` \| `active` \| `archived` |
| `version` | string \| `n/a` |
| `version_source` | `package.json` \| `pyproject` \| `cargo` \| `git-tag` \| `none` |
| `purpose` | one line |
| `updated` | `YYYY-MM-DD` |
| `links` | optional map (specs, roadmap) |

### Body

```markdown
## Backlog
- [ ] (P2) short description of the work — added 2026-06-27

## Future plans
free-form notes
```

Backlog lines are append-only and tolerant of em/en/ascii dashes. A `Plan:` reference at the
end of an item links it to an implementation plan (portfolio-wide convention).

> The `version`/`version_source` are auto-detected from the repo; `purpose` is the one field
> a human writes. The toolkit **never overwrites human-written fields** — it fills only blanks.

---

## How it's enforced

Enforcement is **visibility-based, not blocking** — the system surfaces drift as a worklist
rather than stopping you from working. Four mechanisms:

1. **`lint` (per-repo validator)** — checks one repo's `PROJECT.md`. Findings:

   | code | severity | meaning |
   |------|----------|---------|
   | `missing_manifest` | FAIL | no `PROJECT.md` |
   | `bad_yaml` | FAIL | frontmatter won't parse |
   | `missing_field` | FAIL | a required field is blank |
   | `bad_enum` | FAIL | `tier`/`status`/`version_source` has an invalid value |
   | `not_git` | FAIL (active) / WARN (parking) | repo isn't a git repo |
   | `malformed_item` | WARN | a backlog line doesn't parse / has a bad date |
   | `aged_item` | WARN | a backlog item older than 180 days |
   | `stale_manifest` | WARN | manifest `updated` lags repo HEAD by >30 days (surfaced by scan) |

2. **Session Stop-hook (`portfolio-nudge.sh`)** — at the end of any Claude Code session, if
   the session's repo has a missing/invalid `PROJECT.md`, it prints a non-blocking nudge.

3. **Daily scan (LaunchAgent, 03:00)** — regenerates the rollup and surfaces the FAIL/WARN
   counts across the whole portfolio. New repos appear as `missing_manifest` FAILs — that's
   the signal to onboard them.

4. **Agent convention (`CLAUDE.md`)** — `~/Projects/CLAUDE.md` and `~/Developer/CLAUDE.md`
   tell any agent working in a repo that pending work lives in `PROJECT.md` under `## Backlog`,
   so it's read at session start and new items are captured via the toolkit, not hand-edited.

The steady-state baseline is a fixed set of FAILs (intentionally-uncatalogued scratch dirs)
and WARNs (non-git parking stubs). Health = watching for *movement* off that baseline.

---

## The tools

Run via a zero-install Python package (`PYTHONPATH=… python3 -m portfolio`) plus four shell
wrappers in [`integrations/`](integrations/). Full usage: **[`integrations/README.md`](integrations/README.md)**.

| Tool | Purpose |
|------|---------|
| `portfolio-init.sh` | Onboard a repo — scaffold its `PROJECT.md` (idempotent, no clobber) |
| `portfolio-scan.sh` | Refresh the rollup (`portfolio.json` + `PORTFOLIO.md`); runs daily 03:00 |
| `portfolio-triage.sh` | Walk the inbox and assign captured items into a repo's backlog |
| `portfolio-nudge.sh` | Session Stop-hook (automatic) — warns on a missing/invalid manifest |
| `backlog` skill | Lets agents capture items mid-session via `portfolio add` ([`integrations/backlog.skill.md`](integrations/backlog.skill.md)) |

Underlying CLI subcommands: `init`, `lint`, `add`, `triage`, `scan`, `query`.

---

## Day-to-day (human workflow)

Assuming agents manage their own backlogs (capture/check-off as they work), the recurring
human tasks are small:

```bash
# refresh the picture (also runs automatically daily at 03:00)
~/Projects/project-standards/integrations/portfolio-scan.sh
open ~/.portfolio/PORTFOLIO.md          # per-project table + unified backlog

# place any stray captures the system couldn't auto-route
~/Projects/project-standards/integrations/portfolio-triage.sh

# onboard a new repo when the scan flags one as missing_manifest
~/Projects/project-standards/integrations/portfolio-init.sh /path/to/repo --purpose "does X"
```

See [`integrations/README.md`](integrations/README.md#where-init-fits-in-the-project-lifecycle)
for where `init` best fits in a project's lifecycle.

---

## Foundation conformance matrix

A repo × standard conformance matrix for **foundational repos** — those that provide standards,
tooling, or critical infrastructure to the rest of the portfolio. The matrix answers: do the
foundation repos themselves comply with their own standards?

**What it shows:** a matrix with rows = repos, columns = standards (`project`, `security`,
`code`, `infra`), cell values = compliance state, plus a separate machine-scope
`governance` line (not a matrix column — governance is scoped to the portfolio as a
whole, not to any one repo). Each cell resolves to one of:

| Symbol | Meaning |
|--------|---------|
| ✅ | Passes the standard |
| ❌ | Violates the standard (work required) |
| ⚠ | Violation accepted via `foundation-exceptions.toml` (tracked, revisit trigger) |
| — | Not applicable (standard is not declared in that repo's `applicable_standards`) |
| ? | Unknown (checker timed out, failed, or report is stale — indicates work item, not failure) |

Exit codes: **0** = no violations; **1** = any violation exists; **2** = internal error (malformed
exceptions file, no foundational repos found). Unknown cells do not fail the exit code — they're
flagged in a "Work items" section for visibility.

**Usage:**

```bash
PYTHONPATH=src python3 -m portfolio foundation [--roots ...]
```

The command generates two artifacts:

- **`~/.portfolio/foundation.json`** — Full report: summary (pass/violation/accepted/unknown counts),
  matrix cells with details, audit trail of matched exceptions, stale exceptions.
- **`~/.portfolio/FOUNDATION.md`** — Markdown digest: matrix table, Violations section, Accepted
  exceptions section, Unknown/work-items section, Stale exceptions hygiene.

**Census (frontmatter in each foundational repo's `PROJECT.md`):**

- `foundation: true` (bool) — declares this repo as foundational
- `applicable_standards` (list of str) — subset of `[project, security, code, infra]` — which
  standards this repo declares as in-scope (governance is always included for foundational repos)
- `coolify_resources` (list of str) — app names or DB UUIDs from Coolify that participate in
  the `infra` check; required if `infra` is in `applicable_standards`

**Checker adapters:**

- **project:** reuses the portfolio lint validator; FAILs become violations, WARNs are included in details.
- **security:** runs security-scan against the repo; BLOCK-level findings become violations.
- **code:** checks for code-standards enrollment (`.code-standards.toml` present); missing creates
  `code.not-onboarded` violation; else invokes `code-standards check`.
- **governance:** runs security-scan governance verification across the entire portfolio; failures
  are violations scoped to `_machine` (governance is machine-level, not per-repo).
- **infra:** consumes the latest infra-drift report from `$INFRADRIFT_REPORT_DIR` (default
  `~/infra-drift/reports`); matches proposals by resource name/UUID against `coolify_resources`;
  `ok: false` instances and backup gaps (rule 572) appear as violations.

**Exceptions workflow:**

Edit `foundation-exceptions.toml` at the repo root to accept known/deliberate violations:

```toml
[[exception]]
repo = "brain"
standard = "code"
finding = "C901:*"                       # fnmatch globs supported
reason = "high complexity in legacy module, refactoring Q3"
added = "2026-07-02"
revisit = "After refactoring complete"   # optional, recommended
```

The matrix **reports stale exceptions** — entries that match no current violation — which
surfaces when accepted risks have been resolved and the exception can be deleted.

**Configuration (env overrides):**

| Env var | Default | Purpose |
|---------|---------|---------|
| `SECURITY_STANDARDS_REPO` | `~/Projects/security-standards` | Path to security-standards repo |
| `CODE_STANDARDS_REPO` | `~/Developer/code-standards` | Path to code-standards repo |
| `INFRADRIFT_REPORT_DIR` | `~/infra-drift/reports` | Directory containing infra-drift reports (date-named JSON files) |
| `FOUNDATION_EXCEPTIONS` | `./foundation-exceptions.toml` | Path to exceptions file |
| `FOUNDATION_TIMEOUT` | `120` | Checker timeout in seconds |
| `INFRA_MAX_AGE_HOURS` | `36` | Max age of infra-drift report before marked unknown |

---

## Where things live

| What | Location |
|------|----------|
| Source of truth (per repo) | `<repo>/PROJECT.md` (committed) |
| Rollup digest | `~/.portfolio/PORTFOLIO.md` (derived, regenerated) |
| Rollup data | `~/.portfolio/portfolio.json` (derived, regenerated) |
| Inbox | `~/.portfolio/inbox.jsonl` |
| Scan log | `~/.portfolio/scan.log` |
| Daily scan schedule | `~/Library/LaunchAgents/com.devon.portfolio-scan.plist` (03:00) |
| Backlog skill (installed) | `~/.claude/skills/backlog/SKILL.md` |
| Nudge hook (installed) | `~/.claude/hooks/portfolio-nudge.sh` + registered in `~/.claude/settings.json` |

---

## Architecture & internals

A pure validator is the shared core, consumed by `init`, `add`, `triage`, `scan`, and the
session hook. The package lives in `src/portfolio/`:

| module | role |
|--------|------|
| `schema.py` | frontmatter constants + pure `validate_frontmatter()` |
| `manifest.py` | parse/render `PROJECT.md`; append-only backlog |
| `detect.py` | name/version/remote/git/purpose detection (exception-safe) |
| `validator.py` | `lint(repo)` — the shared core |
| `init.py` | idempotent scaffold/repair |
| `inbox.py` / `add.py` / `triage.py` | inbox-first capture + triage |
| `aggregate.py` / `scan.py` / `query.py` | records, rollup, filtering |
| `cli.py` | argparse dispatch |

Tests: `pytest -q` (run from the repo root). Full task-by-task build is in the
[implementation plan](docs/superpowers/plans/2026-06-25-project-standards.md).

---

## Install (per machine, one-time)

The standard is per-repo (`PROJECT.md`), but the *tooling* installs once per machine:

```bash
bash ~/Projects/project-standards/integrations/install.sh
# then register portfolio-nudge.sh as a Stop hook in ~/.claude/settings.json
```

This installs the `backlog` skill, the nudge hook, and the daily-scan LaunchAgent. It is
**not** a per-repo step — onboarding individual repos is `portfolio-init.sh`.

---

## Related standards

This repo is the project-state/backlog member of a small family of portfolio-wide standards:

- **`~/Projects/security-standards`** — BWS secret-handling, enforced by PreToolUse/Stop hooks.
- **`~/Developer/code-standards`** — coding standards (`STANDARDS.md`); run `/code-review`
  against them before declaring non-trivial code changes done.

Each is a deliberate twin: a standard + the tooling that enforces it.
