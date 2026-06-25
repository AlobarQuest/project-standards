# Project Standards — Unified Portfolio State & Backlog

**Date:** 2026-06-25
**Status:** Design approved (revised after multi-LLM debate), pending implementation plan
**Repo home:** `~/Projects/project-standards` (standalone, a deliberate twin of `security-standards`)

> **Revision note (2026-06-25):** This spec was stress-tested in a 3-way adversarial review
> (Codex, Copilot, Opus — all returned BUILD-WITH-CHANGES). Five changes were folded in:
> (1) a capture-first **inbox + triage** so capture always succeeds; (2) **workflow-gated `init`**
> so enforcement lives in the happy path, not just a passive scanner; (3) a `portfolio query`
> interface; (4) a backlog-write **concurrency rule**; (5) cleanups (item aging, configurable
> roots, version fallback, non-blocking migration). Debate transcript:
> `~/.claude-octopus/debates/session/001-project-standards-arch/`.

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
| Capture model | **Inbox-first** — capture always lands in a central inbox; `triage` reconciles into the right `PROJECT.md` |
| Enforcement | **Workflow-gated (primary) + weekly scanner (backstop)** — `backlog`/`init` keep manifests current in the happy path; the scanner catches untouched repos |
| Session nudge | Non-blocking Stop-hook warning (secondary signal, not the primary mechanism) |
| View | Aggregator emits canonical JSON → Markdown digest + `query` CLI now; Watchtower consumes the JSON in Phase 2 |
| Filename | `PROJECT.md` at repo root (visible + top-level, like README/CLAUDE.md) |
| Scan cadence | Weekly (matches `security-scan`); also runnable on-demand before reading the digest |
| Tooling home | Standalone `project-standards` repo (separate concern from `security-standards`) |
| Scaffolder & git | **Flag-only** — `init` never runs `git init`; the scanner flags non-git repos |
| Derived artifacts | **Central & untracked** — `portfolio.json`, `PORTFOLIO.md`, `inbox.jsonl` in `~/.portfolio/`, not committed |

## Goals / Non-goals

**Goals**
- A single canonical, git-tracked file per project that holds dev-state and backlog.
- Capture that **always succeeds** regardless of cwd correctness or whether the project has a manifest yet.
- Enforcement that lives in the happy path so consistency doesn't rot.
- A derived, queryable, always-truthful unified view (digest + query now, visual map later).

**Non-goals**
- Replacing App Brain (stays the richer business/technical knowledge base for deployed apps).
- Replacing Todoist (personal task manager; this is *project* backlog, repo-scoped).
- A central database as the committed source of truth (repos stay truth; the inbox is a staging/
  reconciliation surface, not the authority for project state).
- Cataloging throwaways with full ceremony (the `parking` tier exists precisely to avoid this).

## Why custom, not GitHub Projects / Linear / Notion

The debate made the strongest off-the-shelf case (GitHub Issues *are* backlog; `gh issue create`
solves capture for the 73% in git; Projects gives a board for free). It was rejected because it
abandons three hard requirements: cover **all 52 including non-git scratch**, **repo-local
durability** as source of truth, and **in-session agent capture** (no tab switch). Off-the-shelf
tools require every project to be an online repo/board and drop the messy long tail that is the
actual pain. We do steal their best idea — *capture always lands centrally* — via the inbox, and
leave room for an optional per-repo `gh issue create` mirror (deferred).

## Architecture

```
   Capture (always succeeds)            Source of truth (repos)         Derived views (read-only)
┌──────────────────────────┐        ┌─────────────────────────┐
│ backlog skill            │        │ /Projects/contacts/      │     portfolio scan
│ "put that on the         │        │   PROJECT.md  ◄──────────┼──┐  (on-demand + weekly LaunchAgent)
│  backlog"                │        │ /Projects/veritok/       │  │       │
│   │                      │        │   PROJECT.md             │  ├─reads─┤─► portfolio.json (aggregate)
│   ├─ high confidence ────┼───────►│ /Developer/.../          │  │       │       │
│   │   write-through      │        │   PROJECT.md             │  │       ├─► PORTFOLIO.md (digest)
│   │                      │        └─────────────────────────┘  │       ├─► portfolio query (CLI)
│   └─ low/ambiguous ──┐   │                 ▲                    │       └─► Watchtower (Phase 2)
│                      ▼   │     triage       │ writes
│            ~/.portfolio/inbox.jsonl ────────┘ (assign item → repo,
│            (staging + central write surface)   init manifest if absent)
└──────────────────────────┘
        ▲                                  ┌─────────────┐
        │ falls back here on dirty/        │  validator  │ ← one pure check, callers:
        │ conflicted tree or no manifest   │  (lint)     │   scan, backlog-skill pre-write,
                                           └─────────────┘   session-nudge hook, triage
```

### Components (each one job, well-bounded)

1. **The standard** — documented `PROJECT.md` schema + inbox/backlog grammar + tier rules. The
   contract every other unit depends on.

2. **`portfolio` CLI** (Python, `python -m portfolio.cli`, mirroring the `security_scan` layout):
   - `init <repo>` — scaffold or repair a `PROJECT.md`, pre-filling detectable fields: `name` from
     dir; `version` from `package.json`/`pyproject.toml`/`Cargo.toml`/git tags, else `n/a` with a
     `version_source: none` note (no silent blanks); git remote; `purpose` from README first line or
     App Brain. Idempotent: never clobbers human-written fields. **Never runs `git init`.** Fast
     enough to be called inline by the backlog skill.
   - `lint <repo>` — the **pure validator** (conforming / list of violations). Shared by scan,
     the backlog-skill pre-write check, the session hook, and triage.
   - `add "<text>" [--repo R] [--priority P#]` — **capture entry point.** Always appends to
     `~/.portfolio/inbox.jsonl` with `{ts, text, inferred_repo, confidence, source_session, priority}`.
     If the repo is unambiguous and the working tree is clean, it *also* write-through-appends to
     that repo's `PROJECT.md` (running `init` first if the manifest is absent) and marks the inbox
     item `triaged`. Otherwise the item stays untriaged.
   - `triage` — review untriaged / low-confidence inbox items; assign each to a repo and write it
     into that `PROJECT.md` (init if absent). Interactive; supports duplicate detection via item IDs.
   - `scan [--roots ...]` — walk the configured roots (default `/Projects` + `/Developer`,
     overridable), run the validator on each repo, emit the report **and** write `portfolio.json` +
     `PORTFOLIO.md`. Flags: missing/malformed/stale manifest, non-git (per tier), and **backlog
     items older than a threshold** (aging).
   - `query [--tier --status --tag --stale --has-backlog ...]` — filter/sort over `portfolio.json`
     so "see all my projects" is interactive, not a manual grep of the digest.

3. **Drift scanner (backstop)** — `portfolio scan` wrapped in a `com.devon.portfolio-scan`
   LaunchAgent, weekly, read-only. Writes the JSON aggregate + `PORTFOLIO.md` to `~/.portfolio/`,
   untracked, regenerated each run. **Demoted from primary mechanism to a backstop** that catches
   repos the workflow never touched. Mirrors `com.devon.security-scan`.

4. **`backlog` capture skill** — triggered by "put that on the backlog" / "/backlog". Calls
   `portfolio add`. This is the **primary enforcement mechanism**: capture auto-creates/validates
   the manifest as a side effect of the thing Devon already wants to do, so consistency is produced
   by the happy path rather than by after-the-fact nudges. (This is "make the right thing automatic,"
   not an approval gate — consistent with the "over-gating breaks usability" rule.)

5. **Session-nudge hook** — a Claude Code **Stop** hook: if the session edited a repo, run the
   validator and emit a *non-blocking* warning if `PROJECT.md` is missing/stale. Secondary signal.

### Concurrency / write-safety rule
Backlog writes to `PROJECT.md` are **append-only under the `## Backlog` heading** — never reorder
or rewrite existing lines, so concurrent edits and dirty trees don't corrupt state. If the working
tree is conflicted/rebasing or the target is ambiguous, `add` does **not** touch `PROJECT.md`; the
item lives in the inbox until `triage`. This bounds the worst case to "an item is in the inbox,"
never "a clobbered manifest."

### Relationship to existing systems
- **App Brain** — unchanged as the richer knowledge base. `PROJECT.md` owns dev-state and is the
  only record for the long tail. The digest **flags divergence** between an app's App Brain
  description and its `PROJECT.md` purpose (cheap drift signal); full sync is Phase 3.
- **Watchtower** — Phase 2 consumer of `portfolio.json`.
- **Todoist / Open Brain** — untouched; different concern.

## The manifest — `PROJECT.md` at repo root

One file, two audiences: YAML frontmatter for the aggregator, markdown body for the human.

```markdown
---
name: contacts
tier: active            # active | parking
status: active          # idea | in-progress | active | archived
version: 0.4.2          # or n/a
version_source: package.json   # package.json | pyproject | cargo | git-tag | none
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
- **Required (tier `active`):** `name`, `tier`, `status`, `version`, `version_source`, `purpose`,
  `updated`. `links` optional.
- **Required (tier `parking`):** `name`, `tier`, `status`, `purpose`. No version/backlog ceremony.
- `status` ∈ `{idea, in-progress, active, archived}`.
- **Backlog items** are markdown checkboxes: `- [ ] (P#) text — added YYYY-MM-DD`. Priority/date
  optional but recommended; the aggregator parses open-count, priority distribution, and age.

### Validator findings (severity)
- **FAIL** (tier `active`): missing `PROJECT.md`; missing required field; malformed frontmatter; not in git.
- **WARN**: stale `updated` vs HEAD; malformed backlog line; backlog item older than threshold;
  `parking` repo not in git (soft); App Brain ⇄ purpose divergence.
- **OK**: conforming.

## Derived outputs (all in `~/.portfolio/`, untracked)
- **`portfolio.json`** — canonical aggregate (per project: frontmatter + parsed backlog stats +
  git staleness + validator status), regenerated each scan. Every view derives from it.
- **`PORTFOLIO.md`** — human digest: sortable table (name, tier, version, status, open-backlog
  count, staleness) + full merged backlog grouped by project + **count of untriaged inbox items**.
- **`inbox.jsonl`** — capture staging + central write surface; drained by `triage`.
- **`portfolio query`** — interactive filter/sort over `portfolio.json`.
- **Watchtower (Phase 2)** — reads `portfolio.json` for its grid + graph.

## Build phases

- **Phase 0 — Standard + validator + scaffolder + capture.** Define the schema; build `init`,
  `lint`, `add` (inbox + write-through), and the `backlog` skill. Roll out: scaffold `PROJECT.md`
  across the ~23 active projects; tier-triage the long tail (parking gets `name`+`status`+`purpose`
  only). **Migration is non-blocking:** active-set purposes can be backfilled incrementally and do
  NOT gate Phase 1 — the scanner/query simply show what's not yet filled.
- **Phase 1 — See everything.** `portfolio scan` → `portfolio.json` + `PORTFOLIO.md`; `query`;
  `triage`; the weekly LaunchAgent; the session-nudge hook. **Milestone: the original ask is met.**
- **Phase 2 — Watchtower consumes `portfolio.json`** (grid/graph auto-truthful).
- **Phase 3 (optional, later)** — App Brain ⇄ `PROJECT.md` sync; optional per-repo `gh issue create`
  mirror for GitHub repos.

## Open / deferred items
- App Brain purpose sync direction (Phase 3, optional).
- Optional `gh issue create` capture mirror for GitHub-hosted repos (Phase 3, opt-in per repo).
