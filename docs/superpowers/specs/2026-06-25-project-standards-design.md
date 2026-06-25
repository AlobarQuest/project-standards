# Project Standards — Unified Portfolio State & Backlog

**Date:** 2026-06-25
**Status:** Design approved, pending implementation plan
**Repo home:** `~/Projects/project-standards` (standalone, a deliberate twin of `security-standards`)

## Problem

Devon runs ~52 projects across `/Users/devon/Projects` (48) and `/Users/devon/Developer` (4).
Work is discovered mid-session ("put that on the backlog") and written down inconsistently or
not at all, scattered across directories. There is no single place to see, for every project:
what it does, what version it's on, its lifecycle status, its open backlog, and its future plans.

Two failures, equally weighted:
- **Capture** — "put that on the backlog" doesn't reliably land anywhere findable or consistent.
- **Visibility** — no aggregated cross-project view of state + backlog.

### Landscape (survey, 2026-06-25)

The portfolio is two populations, not one:
- **~23 "real" portfolio apps** — already in App Brain, mostly git + README + `docs/`, actively
  committed.
- **~29 long-tail experiments/scripts** — **14 of 52 are not in git**; many have no README, no
  version, no docs.

Hard numbers that shaped the design:
- 73% git repos / 27% not in git.
- README coverage 57%; explicit version tracking 48% (heterogeneous: ~12 npm, ~12 python, 4 git-tags).
- Backlog convention is effectively greenfield: only **2 of 52** use a `BACKLOG` file today;
  **11** use the emerging `docs/superpowers/specs` convention.
- App Brain covers the ~23 real apps but **not** the long tail — the coverage hole is exactly
  where things are messiest.

## Decisions (locked)

| Decision | Choice |
|---|---|
| Source of truth | **Repo-local** — one canonical `PROJECT.md` per repo |
| Coverage | **Everything, tiered** — `active` portfolio vs `parking` lot |
| Enforcement | **Both** — weekly drift scanner (LaunchAgent) **+** non-blocking session-end nudge hook |
| View | Aggregator emits canonical JSON → Markdown digest first; Watchtower consumes the JSON in Phase 2 |
| Filename | `PROJECT.md` at repo root (visible + top-level, like README/CLAUDE.md) |
| Scan cadence | Weekly (matches `security-scan`) |
| Tooling home | Standalone `project-standards` repo (separate concern from `security-standards`) |

## Goals / Non-goals

**Goals**
- A single canonical, git-tracked file per project that holds dev-state and backlog.
- Tooling that *requires* consistency across all repos (scaffold, validate, scan, nudge).
- A derived, always-truthful unified view (digest now, visual map later).
- Low-friction capture during agent sessions.

**Non-goals**
- Replacing App Brain (stays the richer business/technical knowledge base for deployed apps).
- Replacing Todoist (personal task manager; this is *project* backlog, repo-scoped).
- A central database as source of truth (explicitly rejected — repos are truth).
- Cataloging throwaways with full ceremony (the `parking` tier exists precisely to avoid this).

## Architecture

```
The repo is source of truth          Derived views (read-only)
┌─────────────────────────┐
│  /Projects/contacts/     │          portfolio scan
│    PROJECT.md   ◄────────┼──┐       (LaunchAgent, weekly)
│  /Projects/veritok/      │  │            │
│    PROJECT.md            │  ├──► reads ──┤──► portfolio.json  (canonical aggregate)
│  /Developer/.../         │  │            │         │
│    PROJECT.md            │  │            ├──► PORTFOLIO.md   (digest: table + merged backlog)
└─────────────────────────┘  │            └──► Watchtower      (Phase 2: card grid + graph)
         ▲                    │
         │ writes well-formed │ reads
   ┌─────┴──────┐       ┌─────┴───────┐
   │ backlog    │       │  validator  │  ← one pure check, three callers:
   │ skill      │       │             │     scan, session-nudge hook, lint CLI
   └────────────┘       └─────────────┘
```

### Components (each one job, well-bounded)

1. **The standard** — documented `PROJECT.md` schema: frontmatter fields, backlog grammar, tier
   rules. Lives in this repo's README/docs. The contract every other unit depends on.

2. **`portfolio` CLI** (Python, invoked `python -m portfolio.cli`, mirroring the `security_scan`
   package layout). Subcommands:
   - `init <repo>` — scaffold or repair a `PROJECT.md`, pre-filling what it can detect: `name`
     from dir, `version` from `package.json`/`pyproject.toml`/`Cargo.toml`/git tags, git remote,
     `purpose` from README first line or App Brain description where available. Idempotent: never
     clobbers human-written fields, only fills blanks/repairs structure.
   - `lint <repo>` — the **pure validator**. Input: a repo path. Output: `conforming` or a list of
     violations. This single function is the shared dependency of the scanner and the session hook.
   - `scan [roots...]` — walk `/Projects` + `/Developer`, run the validator on each repo, emit the
     report (non-conforming repos) **and** write `portfolio.json` + `PORTFOLIO.md`.

3. **Drift scanner** — `portfolio scan` wrapped in a `com.devon.portfolio-scan` LaunchAgent,
   weekly, read-only. Reports every repo with a missing / malformed / stale manifest. Writes the
   JSON aggregate to a known path (e.g. `~/.portfolio/portfolio.json`) and the `PORTFOLIO.md`
   digest. Mirrors the `com.devon.security-scan` pattern Devon already trusts.

4. **Session-nudge hook** — a Claude Code **Stop** hook. If the session edited files in a repo,
   run the validator; if `PROJECT.md` is missing or stale relative to the work just done, emit a
   **non-blocking** warning ("PROJECT.md not updated — consider logging backlog items / bumping
   status"). Never hard-blocks (honors the "security over-gating breaks usability" rule).

5. **`backlog` capture skill** — triggered by "put that on the backlog" / "/backlog". Appends a
   well-formed item to the current repo's `PROJECT.md` Backlog section, creating the file via
   `init` if absent. The agent owns the writing, so format is consistent every time.

### Relationship to existing systems
- **App Brain** — unchanged. `PROJECT.md` owns dev-state (version, status, tier, backlog, plans)
  and is the *only* record for long-tail projects App Brain doesn't track. Phase 3 (optional) adds
  a cross-check between the two.
- **Watchtower** — Phase 2 consumer of `portfolio.json`; its card grid + React Flow graph become
  derived-from-repos instead of hand-maintained.
- **Todoist / Open Brain** — untouched; different concern (personal tasks / thoughts, not project
  backlog).

## The manifest — `PROJECT.md` at repo root

One file, two audiences: YAML frontmatter for the aggregator, markdown body for the human.

```markdown
---
name: contacts
tier: active            # active | parking
status: active          # idea | in-progress | active | archived
version: 0.4.2          # or n/a
purpose: Self-hosted inbound-only contact hub with reconciliation + connector sync.
updated: 2026-06-25     # scanner flags if far behind git HEAD
links:
  specs: docs/superpowers/specs
  roadmap: docs/ROADMAP.md
---

## Backlog
- [ ] (P2) Add CardDAV delete-propagation — added 2026-06-20
- [ ] (P3) Dedupe UI for merge queue — added 2026-06-18

## Future plans
Free text and/or links to specs above.
```

### Schema rules
- **Required (tier `active`):** `name`, `tier`, `status`, `version`, `purpose`, `updated`.
  `links` optional.
- **Required (tier `parking`):** `name`, `tier`, `status`, `purpose`. No version/backlog ceremony.
- `status` ∈ `{idea, in-progress, active, archived}`.
- **Backlog items** are plain markdown checkboxes: `- [ ] (P#) text — added YYYY-MM-DD`. The `(P#)`
  priority and `added` date are optional but recommended; the aggregator parses open-count,
  priority distribution, and age from them.
- **`updated`** is compared to git HEAD date by the scanner; a large gap is a "stale" warning.

### Validator findings (severity)
- **FAIL** (tier `active`): missing `PROJECT.md`; missing required frontmatter field; malformed
  frontmatter; not in git.
- **WARN**: stale `updated` vs HEAD; malformed backlog line; tier `parking` repo not in git (soft).
- **OK**: conforming.

## Derived outputs

- **`portfolio.json`** — canonical aggregate (one record per project: all frontmatter + parsed
  backlog stats + git staleness + validator status). The single artifact every view derives from.
- **`PORTFOLIO.md`** — human digest rendered from the JSON: a sortable table (name, tier, version,
  status, open-backlog count, staleness) followed by the full merged backlog grouped by project.
- **Watchtower (Phase 2)** — reads `portfolio.json` to populate its grid + graph.

## Build phases

- **Phase 0 — Standard + validator + scaffolder.** Define the schema; build `init` and `lint`.
  Bulk-scaffold `PROJECT.md` across the ~23 active projects, then a manual pass to write real
  one-line purposes (pulled from App Brain where it exists). Triage the long tail into
  `active` vs `parking`.
- **Phase 1 — See everything.** `portfolio scan` → `portfolio.json` + `PORTFOLIO.md`; the
  LaunchAgent; the `backlog` skill; the session-nudge hook. **Milestone: the original ask is met.**
- **Phase 2 — Watchtower consumes `portfolio.json`** (grid/graph auto-truthful).
- **Phase 3 (optional, later)** — App Brain ⇄ `PROJECT.md` cross-check for drift.

## Open / deferred items
- Exact `portfolio.json` path and whether the digest is committed per-repo or written to a central
  location only — settle during planning.
- Whether `init` should `git init` non-git scratch dirs automatically or only flag them — lean
  toward flag-only (don't mutate repos as a side effect of scaffolding).
- App Brain purpose sync direction (Phase 3).
