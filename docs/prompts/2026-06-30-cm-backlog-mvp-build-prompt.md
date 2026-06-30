# Build prompt — Change Manager: ingest & display portfolio backlog (MVP)

> Hand this to a build session **inside the `change-manager` repo.** It is self-contained:
> the backlog system is an external producer; you only need the contract below, not its
> internals.

---

## Context

Change Manager already renders a contract of infra-remediation work items for human
review. We are adding a **second, read-only work-source**: the portfolio **backlog** —
open work items across all of Devon's projects, each living in that project's repo-root
`PROJECT.md`.

A local producer (the `portfolio` toolkit on Devon's Mac) scans those files on a schedule
and **POSTs a JSON contract** to Change Manager. Your job is to **ingest that contract and
display it read-only.** No agents, no actions, no write-back — this is the view layer (L0)
of a larger lifecycle that will add per-item spec/plan/implement triggers later, so leave
structural room for that without building it.

This mirrors how CM already consumes the infra escalations contract. **Follow CM's existing
conventions and reuse the escalations ingest/display patterns** where they fit (Flavor B:
FastAPI + Postgres; UI behind Alobar ID forward-auth).

---

## The contract you will receive

`POST /api/backlog/ingest`, body:

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

Field notes:
- `id` — stable 8-char item identifier (may be `null` for not-yet-migrated items; if `null`,
  key the row on `sha256(repo_path + text)` for display only).
- `priority` — `P1|P2|P3` or absent/`null`.
- `provenance.origin` — `devon-authored | agent-captured | unknown`. **Store and display it
  (a small badge), but it must not change behavior in the MVP.**
- `lifecycle` — placeholder, all `null` now. **Persist it as-is; later it holds per-stage
  artifact links + status.** Do not build UI for it yet, but don't discard it.

---

## Deliverable 1 — ingest endpoint

`POST /api/backlog/ingest`

- **Auth: machine-to-machine bearer token**, NOT Alobar ID forward-auth (this is an API call
  from the Mac, not a browser session). Exempt this path from forward-auth and validate a
  `Authorization: Bearer <token>` against a secret in the environment (sourced from BWS,
  gitignored — follow the repo's existing secret-handling pattern). Reject with 401 on
  mismatch.
- **Idempotent upsert** keyed on `(project, item id)`. Re-ingesting the same contract must
  not create duplicates.
- **Reconciliation:** items present for a project in a previous ingest but **absent** from
  the latest contract should be marked closed/stale (not hard-deleted), so the view reflects
  "open now" while preserving history.
- Validate `schema_version` (accept `1`); log + 422 on unknown shapes. Return a small
  summary (`projects`, `items_upserted`, `items_closed`).

Suggested tables (adapt to CM conventions): `backlog_projects` (name, repo_path, tier,
status, purpose, last_seen) and `backlog_items` (id, project, priority, text, added, done,
origin, source_session, lifecycle JSON, status, first_seen, last_seen).

## Deliverable 2 — read-only Backlog screen

- A new **Backlog** view in the CM UI (behind the existing Alobar ID forward-auth, like the
  rest of CM).
- **Grouped by project**; each project expandable to its **open** items showing priority,
  text, added date, status, and a small provenance badge.
- Project header shows open-item count and tier. Sensible default sort (priority then added).
- **Filters:** by tier (active/parking) and priority. Optional simple text search.
- Read-only. **No action buttons.** But lay out item rows so a future per-item action column
  (spec/plan/implement) can be added without restructuring.

---

## Acceptance criteria

1. Posting the sample contract with a valid token populates the tables; an invalid/absent
   token returns 401.
2. Re-posting the same contract is a no-op (no duplicate items); posting a contract with an
   item removed marks that item closed/stale.
3. The Backlog screen lists every open item grouped by project, with counts matching the
   contract, behind forward-auth.
4. `provenance` and `lifecycle` are persisted; provenance shows as a badge; lifecycle is
   stored but unused.
5. No write-back to any external system; no agent execution; the bearer secret is not
   committed.

---

## Explicitly NOT in this build

- No spec/plan/implement triggers or headless agents (later layers).
- No editing backlog items or writing back to `PROJECT.md` (the producer owns the source of
  truth).
- No acting on `provenance` beyond displaying it.

---

## Coordination contract (what the producer side guarantees)

The `portfolio` toolkit will: assign stable item IDs, emit `~/.portfolio/backlog.json` in
the shape above on each scan, and POST it to the agreed `/api/backlog/ingest` URL with the
shared bearer token. **Confirm the endpoint path + token exchange with Devon before wiring
the push.** Schema changes will bump `schema_version`.
