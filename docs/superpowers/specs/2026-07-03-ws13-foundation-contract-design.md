# WS-1.3 — foundation_contract versioning + portfolio-wide conformance matrix

**Date:** 2026-07-03
**Workstream:** Software factory Phase 1, WS-1.3 (master plan line 138; companion §3.7)
**Owning repo:** project-standards
**Status:** Approved design, pre-implementation

## Goal

Extend WS-0.0's PROJECT.md declaration (`foundation: true` + `applicable_standards`)
into the full `foundation_contract`: standards **versions**, **required_checks**,
and **exceptions** in the frontmatter block. Widen the conformance matrix from the
foundational set (8 repos, `portfolio foundation`) to the whole portfolio
(per-repo compliance state in `portfolio scan`). Nothing else — WS-1.4 (brain
governance) and WS-0.3 (code-standards rollout) are separate workstreams.

## Exit criteria (companion §3.7 slice)

- Every foundation repo's PROJECT.md exposes applicable standards WITH versions +
  required_checks + exceptions.
- `portfolio scan` reports per-repo compliance state across the whole portfolio
  (pass / violation / accepted-exception / not-applicable / unknown; unknown cells
  are findings, not silence).
- The WS-0.0 foundational matrix still passes under the new schema.
- A version bump in one standard is visible as drift in consuming repos'
  compliance state.

## Decisions (settled with Devon 2026-07-03)

| Decision | Choice | Rationale |
|---|---|---|
| Version source | One-line `STANDARD_VERSION` file at each standards repo root, starting `1.0` | pyproject tracks the TOOL; a scanner bugfix must not mark every consumer drifted. Date-based collides within a month; git tags need git invocations and are forgettable. |
| Exceptions home | Per-repo PROJECT.md frontmatter; central `foundation-exceptions.toml` retained for machine/governance scope only | Matches §3.7's manifest; the exception travels with the repo it excuses; the central file had zero entries so migration was free. |
| Exception expiry | Optional `review_by` date; when passed, the exception stops masking | Some exceptions are permanent-until-trigger; `revisit` text stays as the qualitative counterpart. |
| Un-onboarded repos | `unknown` cells + explanatory note; report, never block | Stays inside the five-state vocabulary; distinguishes causes via notes; N/A would make "never got to it" look like "consciously exempt". |
| required_checks depth | Static wiring verification | Deterministic, no network. Catches "declared but wired nowhere". See Limitations for what it does NOT catch. |
| Architecture | Approach A: shared compliance core, two consumers | `portfolio foundation` keeps exact behavior/outputs; `portfolio scan` gains compliance; LaunchAgent unchanged. |
| Schema shape | `applicable_standards` upgraded list → mapping std→version; flat keys, no nested block | A parallel `standards_versions` map could disagree with the list; the companion's nested block is labeled "possible manifest", not binding. List form stays parseable. |

## 1. Standard versions

- New file `STANDARD_VERSION` (single line, e.g. `1.0`) at the root of:
  `~/Projects/project-standards`, `~/Developer/code-standards`,
  `~/Projects/security-standards`. All start at `1.0`.
- Bumped by hand in the PR that materially changes the standard's requirements
  (new/changed rules), never for tool bugfixes.
- The matrix resolves current versions by reading these files via the repo paths
  already in `config.py`. Missing file → that standard's current version is
  unknown; consumer cells get a note, NOT a drift finding.
- The **infra** standard is unversioned in WS-1.3 (it lives in infra-brain, not a
  repo file). `infra: null` is a legitimate pin. Knowledge/brain versioning is WS-1.4.
- **Semantics: a pin is an acknowledgment, not a behavior selector.** Checkers
  always run the current tools regardless of pin. `security: "1.0"` means "this
  repo has acknowledged security standard 1.0". Drift = "the standard moved and
  this repo hasn't re-acknowledged".

## 2. Frontmatter schema (foundation_contract)

```yaml
foundation: true            # WS-0.0, unchanged
foundation_contract: 1      # schema version marker
applicable_standards:
  project: "1.0"
  security: "1.0"
  code: "1.0"
  infra: null               # applicable; standard unversioned — no finding
required_checks:
  - id: security-scan
    executor: github-actions:security-scan.yml   # or github-actions:<file>:<job>
  - id: session-scan-gate
    executor: hook:bws-scan-gate.sh
exceptions:
  - standard: code
    finding: "code.not-onboarded"    # fnmatch pattern (same matching as today)
    reason: "why this is accepted"
    added: 2026-07-03
    review_by: 2026-09-01            # optional; expiry unmasks
    revisit: "trigger text"          # optional
```

Rules:

- **List form of `applicable_standards` stays parseable** (WS-0.0 compatibility).
  Each listed standard = applicable but unpinned → `<std>.version-unpinned`
  finding. This is the migration nudge; no hard break.
- `null` pin for a standard that HAS a `STANDARD_VERSION` → `version-unpinned`.
- Pinned ≠ current → `<std>.version-drift` finding (message shows both versions,
  covering the pinned-ahead typo case). Both finding kinds are violation-level
  details in that standard's column, maskable by exceptions like any finding.
- `foundation_contract` present with value ≠ 1 → validator FAIL, all cells
  unknown (never guess a future schema).
- `foundation_contract`, `required_checks`, `exceptions` are valid on any repo
  that declares `applicable_standards`, not only `foundation: true` repos
  (WS-0.3 onboarding will reuse the schema).
- `schema.py` lint validates all three new blocks. **A malformed exception entry
  is a FAIL finding and never masks anything** — a broken excuse can't excuse.

## 3. Exceptions resolution

- `resolve_cell` consumes exceptions from the repo's own frontmatter.
- `foundation-exceptions.toml` shrinks to machine/governance scope only (header
  updated). Two mechanisms is a known cost; machine scope has no repo to host it.
- Expired `review_by` → entry stops masking; the now-violation detail carries
  "exception expired (review_by YYYY-MM-DD)".
- Stale detection preserved per repo: frontmatter exceptions matching nothing are
  reported in the digest (same as today's unused-exceptions section).
- **Governance posture, named consciously:** frontmatter exceptions are
  self-attestation — a repo can excuse itself in the PR that introduces the
  violation. Accepted for a solo operator because: every exception in effect is
  listed in BOTH digests (FOUNDATION.md and the PORTFOLIO.md compliance section)
  and re-read at weekly review, and PRs are merged only by Devon. The central
  file's third-party-review property is knowingly traded away.

## 4. required_checks — static wiring verification

Executor grammar and verifiers (all deterministic local reads, no network):

| Executor form | Wiring check |
|---|---|
| `github-actions:<file>[:<job>]` | `.github/workflows/<file>` exists in the repo; if `:job` given, that job key exists in the workflow YAML |
| `hook:<name>` | `<name>` is **registered in `~/.claude/settings.json` hooks config** — NOT mere file existence in `~/.claude/hooks/` (a deployed-but-unregistered hook never runs; deployed ≠ wired) |
| `launchagent:<label>` | `~/Library/LaunchAgents/<label>.plist` exists. Limitation: plist exists ≠ loaded; checking `launchctl` is runtime state and flaky, so file existence is accepted and the gap is stated |

Findings, in a new fifth `checks` matrix column:

- `checks.not-wired` — declared executor's target missing.
- `checks.bad-executor` — unparseable executor string (an unverifiable
  declaration is a violation, not a skip).
- `checks.none-declared` — a `foundation: true` repo with no `required_checks`
  (a foundation repo must state its gates). Non-foundation repos without
  declarations: `—` (not-applicable). Non-foundation repos WITH declarations are
  verified normally.

### Limitation (stated plainly, per design review)

Static wiring verifies the check is *invoked somewhere*, not that it does real
work. **It would NOT have caught the actual quality.yml incident** (workflow
existed, job ran, `make check` had no target, every tool `command -v`-guarded —
passed hollow). WS-1.3 closes "declared but wired nowhere", the biggest lie.
"Wired but runs hollow" needs execution evidence (did it run, did it collect
tests) — a named future drift-loop enhancement, deliberately out of scope. A
`must_contain` substring heuristic was considered and rejected: string-matching
workflow YAML creates false confidence worse than a stated gap.

## 5. Portfolio-wide reach (Approach A)

Extract per-repo cell resolution from `foundation.py` into a new
`compliance.py` core. Two consumers:

- **`portfolio foundation`** — behavior, outputs (foundation.json /
  FOUNDATION.md), and exit-code semantics unchanged (exit 1 on violations). It
  reads the new schema; the `checks` column is added to its matrix.
- **`portfolio scan`** — `ProjectRecord` gains a `compliance` cells dict;
  PORTFOLIO.md gains a compliance-matrix section (including the accepted-
  exceptions-in-effect list); portfolio.json carries the same data.

Per-repo semantics in scan:

- Declared standards → run the real checkers (same code as foundation).
- Undeclared standards → `unknown` + note "standards not declared (pending
  rollout)", **no checker execution** (bounds weekly runtime: checkers only run
  where declarations exist).
- No PROJECT.md at all → all-unknown row noted "no manifest".
- Scan reports, never blocks: its exit semantics are unchanged. Blocking stays
  `portfolio foundation`'s job.

The `com.devon.portfolio-scan` LaunchAgent needs no change (it runs `scan`);
post-implementation verification runs it manually to confirm green.

## 6. Migration (batch, mechanical, truthful)

The 8 `foundation: true` repos (alobar-id, brain, change-manager,
infraops-mcp-server, project-standards, security-standards, vps-backup,
code-standards) get frontmatter upgrades in one pass:

- `applicable_standards` list → map with current pins (`"1.0"` for
  project/security/code; `infra: null` where applicable).
- `foundation_contract: 1`.
- `required_checks` entries **only for checks actually wired today**, verified
  per repo during implementation. The contract must not lie on day one; a repo
  missing a gate shows a finding, which is correct and becomes the work list.

Non-foundation repos: untouched (WS-0.3's rollout). Each edited repo: branch +
PR; PRs wait for Devon's explicit merge signal.

**Drift blast radius, decided consciously:** drift is violation-level, so a
version bump turns all consumers red in the blocking gate until they re-pin.
Kept on purpose — a bump SHOULD create visible work; re-pinning is a batch
mechanical edit done in the bump session. The advisory alternative was rejected
because nothing would ever force re-acknowledgment.

## 7. Error handling

- Malformed frontmatter YAML → unknown cells + finding (extends existing behavior).
- Malformed exception entry → FAIL finding, entry ignored, never masks.
- `STANDARD_VERSION` missing/unreadable → version-unknown note, not drift.
- Unparseable executor → `checks.bad-executor` violation.
- `foundation_contract` ≠ 1 → validator FAIL + unknown cells.

## 8. Testing

Existing foundation tests must pass (WS-0.0 matrix under new schema). New tests:

- Map and list `applicable_standards` parsing; null pins (infra vs versioned std).
- `version-drift` and `version-unpinned` detection; missing STANDARD_VERSION.
- Exception masking, `review_by` expiry unmasking, stale-exception reporting,
  malformed-entry rejection.
- Each executor kind: wired-pass and not-wired-fail; bad executor string;
  `checks.none-declared` on foundation repos; N/A on non-foundation.
- Hook verifier reads settings.json registration (fixture settings.json).
- Scan: undeclared repo → unknown cells without checker execution;
  manifest-less repo → all-unknown row; compliance section rendered.
- End-to-end exit-criterion demo: bump STANDARD_VERSION in a fixture standards
  repo → consumer cell shows drift.

Gates: `make check` green, `/code-review` on the diff, manual `portfolio scan` +
`portfolio foundation` runs, LaunchAgent-equivalent scan run green.

## 9. Out of scope / follow-ups

- **WS-1.4** brain governance columns (live-DB session). **WS-0.3** rollout of
  declarations to non-foundation repos.
- Execution-evidence verification of required_checks (gh api runs/conclusions) —
  future drift-loop enhancement; closes the "wired but hollow" gap.
- **Backlog items to file (3):** per standards repo, a CI guard "if the
  standard's rules changed in this diff, STANDARD_VERSION must change too" —
  without it the versioning system rusts silently (a standard can change without
  any drift appearing anywhere).
- Registry note: WS-1.3 touches no actor vocabulary; if matrix work ever emits
  factory events, actors come from the WS-1.2 registry, never invented here.
