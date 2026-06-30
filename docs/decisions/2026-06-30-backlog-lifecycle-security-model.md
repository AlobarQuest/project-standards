# Backlog item lifecycle — design & security model

**Status:** accepted (design); MVP scoped separately
**Date:** 2026-06-30
**Scope:** how backlog items captured in `PROJECT.md` get turned into specs, plans, and
implementations by headless agents — and the guardrails that make that safe.

---

## Context

The portfolio toolkit now centralizes every project's backlog in repo-root `PROJECT.md`
files, rolled up into one view. The next capability: from a central surface (the existing
**Change Manager**), see all open backlog items and, per item, trigger a headless agent
in the item's home repo to **generate a requirement spec → then a plan → then an
implementation**. Each step is a separate, human-triggered stage.

This is the same shape Change Manager already runs for infrastructure: a contract of work
items, a human gate, and a guarded executor. Backlog is a **second work-source into that
existing review→gate→execute loop**, not a new system.

This document is the up-front guardrail design. It exists so the human gate can be an
**intent decision**, not an on-the-fly code review.

---

## Threat model — the real danger is laundering, not the agent

The lethal trifecta requires untrusted content to reach a consequential action. In this
system untrusted content enters at **capture**: agents create backlog items from what they
read while working — READMEs, email, issue text, web pages — exactly the inputs the
environment's security policy says to treat as hostile data.

The insidious step is **provenance laundering**: once that text becomes "a backlog item,"
it looks human-sanctioned. Its origin ("this came from an email body") is gone. Later a
button feeds it to a write-capable agent *as an instruction*, and the agent acts on it.

> Poisoned content → backlog item (provenance stripped) → autonomous write → real change.

The agent is not the problem. The problem is **text of unknown trust being treated as a
sanctioned instruction with no technical bound between it and a consequential action.**

---

## Principles

1. **Approve goals, bound means.** The human authorizes a *goal* ("fix that stale URL").
   The guardrails bound the *means* such that — regardless of what code is produced in
   service of that goal — the means available across its lifecycle cannot cause
   catastrophic harm. Approval is honestly an intent decision because the blast radius is
   fixed up front, by construction, not by human vigilance.

2. **The pipeline is the mitigation, not the risk.** spec → plan → implement inserts
   reviewable artifacts and a reviewable diff before anything merges. The danger appears
   only if the chain is *collapsed* into "button → implement → deploy." Keep the chain.

3. **Fail safe when the rung below is incomplete.** This capability stands on lower rungs
   (code-standards review, security-standards scanning, runtime least-privilege). It must
   be built so that if a lower rung is incomplete, this one still cannot cause harm —
   never assume a dependency is finished.

4. **Read/propose plane vs. mutate plane.** Every powerful capability is split into a free,
   auditable read/propose plane and a gated, surfaced mutate plane. (infraops already does
   this: read-only planning view + guarded mutations. The backlog pipeline copies it:
   spec/plan = propose; implement-under-gate = mutate.)

---

## The invariant

> **Untrusted text never reaches a consequential action without (a) a machine performing
> the technical adversarial analysis and (b) a human authorizing the goal — between the
> text and the action.**

The human does the *intent* analysis; a machine does the *technical* analysis. Neither is
asked to do the other's job.

---

## Three containment rings (no single ring is load-bearing)

**Ring 1 — author-time capability bound.** The implementation agent is **code-only and
branch-only**: scoped to the one repo, writes to a branch, opens a diff/PR. It has **no
infraops, no BWS/secret access, no deploy, no push-to-main, no arbitrary network egress**,
under the catastrophic deny-list. A poisoned item cannot reach infra or secrets while
authoring; worst case it writes bad code to a branch.

**Ring 2 — automated adversarial gate.** Because the human approves intent (not function
names), a *machine* does the technical review. The PR auto-runs the existing
`/code-review` (code-standards), the `security-standards` scanner, a secret-scan, and a
**diff-risk classifier** that flags means-relevant changes: new network egress, secret/env
access, `subprocess`/`exec`, new dependencies, auth/permission changes, deploy-config
edits. Findings **gate the merge** and **surface to the human as risk flags**, so the
intent approval is *informed* — not a hunt for the malicious line.

> **High-signal requirement:** Ring 2 must be quiet on benign diffs and loud only on
> means-relevant ones. A noisy classifier trains rubber-stamping and defeats itself. The
> classifier's quality is what buys the right to stay at intent altitude.

**Ring 3 — runtime containment (the backstop, external dependency).** Branch code
eventually merges and runs in prod with the app's privileges. The ring that makes "I
approved without reading the code" survivable is **least-privilege at runtime** — scoped DB
users, scoped secrets, egress allow-lists — so malicious merged code is boxed by its
sandbox. This lives in the infra/security standards, **not in the backlog system.** The
backlog pipeline bounds the *author*; bounding the *deployed code* is a separate, ongoing
concern this leans on.

---

## Provenance & graduated trust

- Every item carries **provenance**: `devon-authored` vs `agent-captured` (+ source), so
  rigor scales with trust.
- **The inbox is the trust gate.** Items derived from untrusted/fetched content **never
  auto-write-through** to `PROJECT.md`; they wait in the inbox until the human triages.
  Triage re-attaches provenance and blocks laundering — "yes, this is a task I want." This
  reuses the existing inbox-first machinery.

---

## The fail-safe handoff (how this rung avoids outrunning Ring 3)

The "implement" stage terminates at **PR opened, gates run, flags surfaced.** Merge and
deploy stay inside the existing human + infraops-guard path. **Backlog automation never
auto-merges or auto-deploys** while runtime containment is still maturing. The new rung
*consumes* the rungs that exist (code/security review) and *hands off* to controls already
trusted for the part that depends on the rung still under construction.

---

## Ownership split

| Owner | Responsibility |
|-------|----------------|
| **project-standards** (this repo) | Stable item IDs; the backlog contract; provenance + inbox-as-trust-gate; the **bounded executor** (Ring 1) and running the **automated gates** (Ring 2), emitting risk flags. |
| **Change Manager** | The surface: render items + provenance + artifacts + risk flags; **goal-level** human approval per stage; the audit record. No agent-spawning of its own. |
| **Infra / security standards** (existing) | Ring 3 — runtime least-privilege & egress. The load-bearing backstop, furthest from this system. |

---

## Layering roadmap

- **L0 — View (MVP):** open backlog items visible in Change Manager, read-only. No agents.
  Proves the contract + transport. (See the MVP spec.)
- **L1 — Spec:** one button → headless agent generates a requirement spec to a branch.
  First exercise of the runner; near-zero blast radius (read repo, write a doc).
- **L2 — Plan:** same pattern, chained off the spec.
- **L3 — Implement:** same pattern, but writes code to a branch + runs Ring 2 gates +
  opens a PR. **Stops there** — never merges/deploys (fail-safe handoff).

Each layer reuses the prior's runner. Provenance and the contract are present from L0 even
though L0 doesn't act on them (forward-compatible).

---

## Prerequisite called out

Backlog items have **no durable identity** today — once written to `PROJECT.md` an item is
just a text line. Per-item actions ("trigger spec for *this* item") require a **stable ID
that survives edits and re-scans.** Establishing stable IDs is L0 groundwork and a hard
prerequisite for everything above it. (See the MVP spec.)
