# Spec — Backlog in Change Manager (MVP / Layer 0)

**Date:** 2026-06-30
**Depends on:** [backlog lifecycle security model](../../decisions/2026-06-30-backlog-lifecycle-security-model.md)
**Layer:** L0 — view only. No agents, no actions.

---

## Goal

Devon can open the Change Manager UI and **see every open backlog item across the
portfolio, grouped by project**, read-only. This ships the single pane of glass and proves
the contract + transport that every later layer (spec/plan/implement) builds on.

## Non-goals (explicitly deferred)

- No spec/plan/implement triggers, no headless agents, no buttons that act. (L1–L3.)
- No provenance-based gating behavior (the field ships in the contract but the MVP only
  *displays* it; it does not change behavior).
- No write-back from CM to `PROJECT.md`. CM is a read-only consumer.

---

## Architecture (MVP slice)

```
  PROJECT.md (×N)  ──scan──▶  backlog contract (JSON)  ──push──▶  CM ingest API ──▶ CM "Backlog" screen
   (source of truth)          ~/.portfolio/backlog.json           (Postgres)        (read-only)
```

The Mac scans locally (already daily at 03:00), produces the contract, and **pushes** it to
a Change Manager ingest endpoint — mirroring the existing infra producer→CM pattern (Mac
initiates; the VPS never reaches into the Mac).

---

## project-standards deliverables (this repo)

### 1. Stable item IDs (the hard prerequisite)

Backlog lines gain an embedded, durable ID that survives text edits and re-scans:

```
- [ ] (P2) [#a1b2c3d4] Validate/normalize OpenRouter metadata… — added 2026-06-27
```

- **Mint:** 8 hex chars (`secrets.token_hex(4)`) assigned **once**, at `add`/`triage`
  write time. Never recomputed, so editing the text keeps the identity.
- **Parser:** extend the backlog line regex to accept an optional `[#<8hex>]` token after
  the optional priority; existing lines without one still parse (id = `null`).
- **Backfill:** a new `portfolio backfill-ids` command assigns IDs to existing items that
  lack one, editing each line in place (append-only-safe, controlled mutation; Devon
  commits the result). Run once across the portfolio so the contract carries stable IDs
  from day 1.
- **Scan stays read-only:** `scan` never mutates repos. ID assignment happens only on
  write paths (`add`/`triage`/`backfill-ids`); items still lacking an id surface in the
  contract with `"id": null` (CM keys those on a derived fallback for display only).

### 2. The backlog contract

`portfolio scan` additionally writes `~/.portfolio/backlog.json`:

```json
{
  "generated_at": "2026-06-30T03:00:00",
  "source": "portfolio-scan",
  "schema_version": 1,
  "projects": [
    {
      "name": "brain",
      "repo_path": "/Users/devon/Projects/brain",
      "tier": "active",
      "status": "active",
      "purpose": "Unified knowledge platform…",
      "backlog": [
        {
          "id": "a1b2c3d4",
          "priority": "P2",
          "text": "Validate/normalize OpenRouter-extracted metadata before storing…",
          "added": "2026-06-27",
          "done": false,
          "provenance": { "origin": "unknown", "source_session": null },
          "lifecycle": { "spec": null, "plan": null, "implementation": null }
        }
      ]
    }
  ]
}
```

- `provenance.origin` ∈ `devon-authored | agent-captured | unknown`. MVP existing items =
  `unknown` (can't be retro-determined). Populated going forward by the capture path.
- `lifecycle` is a forward-compatibility placeholder (all `null` in MVP); later holds
  artifact links + per-stage status.
- Only **open** items (`done=false`) are required for MVP; completed items may be omitted.

### 3. Transport (push to CM)

- After writing the contract, the scan **POSTs it** to the CM ingest endpoint.
- Endpoint URL + a machine-to-machine **bearer token** come from a gitignored runtime env
  (token sourced from BWS by stable UUID — never committed; follows the repo's BWS rules).
- Implemented as a step in `portfolio-scan.sh` (or `portfolio export --to <url>`), so the
  daily 03:00 job keeps CM current. Failure to push logs to `~/.portfolio/scan.log` and is
  non-fatal to the scan.

## Change Manager deliverables (separate build — see build-prompt)

- `POST /api/backlog/ingest` — authenticated by the shared bearer token; upserts the
  contract into Postgres (idempotent by item `id`; items absent from the latest contract for
  a project are marked closed/stale).
- A read-only **Backlog** screen: projects (grouped), each expandable to its open items
  showing priority, text, added date, and status. Filterable by tier/priority. Schema and
  layout should leave room for per-item lifecycle/actions later.

---

## Acceptance criteria

1. `portfolio backfill-ids` gives every existing open backlog item a stable `[#id]`; a
   re-run is a no-op; editing an item's text preserves its id.
2. `portfolio scan` writes `~/.portfolio/backlog.json` validating against the schema above,
   and pushes it to the configured CM endpoint (200 response logged).
3. In the CM UI, every open backlog item appears under its project with priority/text/added;
   counts match `~/.portfolio/PORTFOLIO.md`'s "Backlog by project".
4. Re-running the scan after a backlog change is reflected in CM after the next push
   (idempotent upsert — no duplicates).
5. No agents, no actions, no write-back. The push token is never committed.

---

## Out of scope / next

L1 (spec generation) introduces the headless runner, the bounded executor (Ring 1), and the
automated gate (Ring 2) per the security model. The contract's `lifecycle` block and
provenance are already present so L1 is additive, not a reshape.
