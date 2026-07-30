# WS-P2.11 Spec — Conformance Kit + Readiness-as-Proposals

Date: 2026-07-30. Status: APPROVED (Devon, 2026-07-30), amended same day for
**construction mode** (`~/docs/software-delivery-system/2026-07-30-construction-mode-ruling.md`):
ceremony removed, engineering kept. Amendments: §6 canary de-ceremonized; §3 check 6
anchors to a declared pin; escalations follow the construction-mode filter.
Governing handoff: `~/docs/software-delivery-system/2026-07-30-wsp211-conformance-kit-handoff-prompt.md`.
Closeout: per `session-closeout-contract.md` (same directory) — cited, not restated.
Session model: `factory route --surface local-heavy` → fable-5 (verified this session).

## Decisions register (all HQ-approved 2026-07-30)

| # | Decision |
|---|---|
| Q1 | Kit emits a machine-readable remediation queue inside the readiness result; `factory create` grows a flag that consumes it and scaffolds Draft package(s). Kit is read-only. Nothing mints units. |
| Q2 | `portfolio onboard <repo>` in project-standards is the machinery; `factory onboard` in intent-packages is a thin passthrough. |
| Q3 | 7 admission checks + 4 advisory (list in §3); every result names its exact next action. |
| Q4 | Validation targets: change-manager (expected ~clean) + brain (expected real queue). |
| Q5 | Branch protection / runner permissions: check-and-report only. The kit never writes GitHub settings. |
| S-A | "Harmless doc-change certification" = end-to-end canary run — **re-staged by HQ amendment 1, see §6**. |
| S-B | Pin story: kit-side caller template + pin check now; factory-runner's CI/guard P1s stay a separate workstream (named residual). |

HQ amendments folded in: (1) canary re-staged behind its own gate, §6; (2) entry-point
resolved by decision, §5; (3) remediation-queue schema versioned from day one, §4.

## 1. Scope and non-goals

**Builds:** a one-command repo-onboarding readiness check (`portfolio onboard <repo>`) in
project-standards, composing what already exists in project-standards, code-standards,
security-standards, intent-packages, and factory-runner; a versioned machine-readable
readiness result whose failed checks form a remediation queue; a `factory create`
consumer that scaffolds Draft intent packages from that queue; the owned factory-runner
caller template with a live-read pin; validation on two real repos.

**Non-goals (hard):** no orchestrator changes (any design pressure toward one → stop,
return to HQ). No GitHub settings writes (Q5). No canary execution (§6 gate). No
factory-runner CI work (S-B). No onboarding of all five exit-#2 repos (later adoption
work — the closeout names this residual).

**Repos in span (5)** — closeout contract clean-tree/CI table covers each:
- **project-standards** (mutated): the kit, this spec, the caller template asset.
- **intent-packages** (mutated): Step-0 PR #39 (done), `factory onboard` passthrough,
  `factory create --from-readiness`, live-run fixture, WS-P2.11's own intent package.
- **factory-runner** (mutated, one line): the `RECOMMENDED_CALLER_PIN` declaration
  file (§3 check 6). No CI/guard work there (S-B stands).
- **change-manager** (read-only validation target): expected ~clean readiness run.
- **brain** (read-only validation target): expected real remediation queue.

Increments land repo-coherently: no PR mixes repos; cross-repo ordering is
kit-before-consumer so the consumer's fixture can come from a live kit run.

## 2. Architecture

`portfolio onboard <repo>` is a new verb in `src/portfolio/cli.py` (same argparse
pattern as the six existing verbs), delegating to a new `src/portfolio/onboard.py`.
It runs the check set (§3) against one repo and writes a readiness result (§4):

- Reuses the existing result plumbing where it fits: statuses and detail shapes from
  `matrix.py` (`PASS/VIOLATION/…`, `{"id","message"}` details) — but the onboard result
  is per-repo and self-contained, not a `foundation.json` row, because onboarding must
  work on repos that are not yet `foundation: true` (that is the point).
- Reuses existing checkers by composition (`checkers.py::check_*`,
  `validator.lint`, the security scanner's JSON contract, `wiring.py` patterns).
  New checks live beside them in `onboard.py` (or `checkers.py` where they are
  general), each returning the same `CheckResult` shape.
- Exit codes: 0 = all admission checks pass; 1 = any admission failure; 2 = internal
  error. Advisory failures never affect the exit code (mirrors `foundation`).
- Every check result carries `fix`: the exact command(s) or action that clears it —
  the `factory status` lesson (next action named at every step). For checks whose fix
  is repo work (not a setting), the same content is what becomes a remediation item.

The **caller template** is a kit asset: `src/portfolio/templates/factory-runner-caller.yml`
with a `{{FACTORY_RUNNER_WORKFLOW_SHA}}` slot. The template's content is derived at
build time from the only current-shape deployed caller (change-manager's, verified
2026-07-30) — 4 secrets, permissions block, `orchestrator_url` — and the pin slot is
filled at *emission* time from the live source of truth (§3 check 6). It lives in
project-standards, not factory-runner, because (a) it is an onboarding asset consumed
only by the kit, and (b) factory-runner currently has no CI at all — landing a new
must-stay-current artifact in a repo with no gate recreates the wired-but-hollow class
this program keeps paying for. Revisit the home if/when factory-runner's CI P1 lands.

## 3. The check set

Admission (hard-fail; each result names its fix):

1. **`git.current`** — repo has `origin`, `main` is checked out, fetched, HEAD ==
   `origin/main`, worktree clean. Same predicate family as intent-packages'
   `assert_checkout_current` (Step 0), reimplemented in the kit (two lines of git;
   a cross-repo import for this would be a worse coupling than the duplication —
   noted here deliberately).
2. **`project.manifest`** — `validator.lint(repo)` has no FAIL findings (composes the
   existing linter verbatim).
3. **`code.onboarded`** — `.code-standards.toml` present AND vendored
   `.github/workflows/quality.yml` present (presence per `checkers.py::check_code`'s
   manifest rule; the quality.yml check is new — code-standards' own `verify` reports
   drift but never absence, verified in survey).
4. **`ci.executed`** — the most recent quality-workflow run on `main` concluded
   success AND its job log contains `collected N items` with N > 0 for a Python repo
   (via `gh run list` / `gh run view --log`). Never the check color alone: the vendored
   CI is confirmed able to pass having run nothing (all eight tools `command -v`-guarded,
   pytest exit 5 swallowed, no-lockfile repos install nothing). For a repo with no
   tests directory, the check reports its own variant (`no tests to evidence`) as a
   VIOLATION with the fix being "add tests or accept the advisory downgrade at HQ" —
   fail-closed, graduation decided by Devon, not by the kit.
5. **`security.clean`** — scanner JSON `by_severity.BLOCK == 0`; if the repo references
   BWS UUIDs (`manifest.referenced_uuids` non-empty — the scanner's own gating rule),
   `.bws-secrets.toml` must exist and the repo must have a `[[repo]]` consumer entry in
   security-standards' `governance-map.toml`.
6. **`runner.caller`** — `.github/workflows/factory-runner-pilot.yml` exists; its
   `uses:` ref is a full 40-char SHA (never `@main`); that SHA equals the pin
   factory-runner **declares** in a `RECOMMENDED_CALLER_PIN` file at its repo root
   (single line, full SHA; bumped deliberately when a workflow change should
   propagate), read live via
   `gh api repos/AlobarQuest/factory-runner/contents/RECOMMENDED_CALLER_PIN`;
   and the caller's secrets cover the reusable workflow's `secrets:` block **read at
   the declared SHA** (`gh secret list` vs the workflow's required set — never
   hard-coded: the 2-of-4 stale doc template is exactly the copied-shape failure this
   rule prevents). Anchoring to a *declared* pin, not live `origin/main` HEAD, was a
   deliberate re-decision: HEAD-anchoring would fail admission portfolio-wide on every
   runner merge until all callers re-pin (availability coupling to another repo's
   merge timing) and would not even detect the actual GAP-4 defect (workflow-vs-install
   inconsistency at a given SHA). "Behind the declared pin" is the real staleness
   condition. The marker file is a one-line factory-runner PR in this workstream.
7. **`profile.declared`** — the repo's PROJECT.md frontmatter declares a
   `delivery_profile:` whose value is a registered profile name, validated by pointer
   against intent-packages' registry (`PROFILES` keys read from the intent-packages
   checkout / `factory` CLI, never copied — cross-boundary vocabulary rules apply).
   This frontmatter key is new; `schema.py`/`contract.py` accept it as part of this
   workstream.

Advisory (reported, never exit-affecting): **`deps.dependabot`** (config present);
**`repo.protection`** (branch protection on `main`, Devon-only merge — read via gh API,
check-and-report per Q5); **`backlog.hygiene`** (aged items per existing lint WARNs);
**`standards.pinned`** (STANDARD_VERSION drift per existing `compliance.py` synthesis).

Guard discipline (binding, from the handoff): every admission check ships with a test
that constructs a failing instance and proves the check FIRES — a check only ever seen
green is not evidence (`test_unreachable_guards` lesson class).

## 4. The readiness result and remediation queue (amendment 3)

One JSON document, written to `<repo>/.portfolio-readiness.json` is **wrong** — the kit
is read-only against the target. It writes to stdout and (always) to
`~/.portfolio/readiness/<repo-name>.json`, plus a human digest to stderr.

Top-level shape (authoritative schema lives ONLY in project-standards —
`src/portfolio/readiness_schema.py` + a published JSON-schema file
`schema/portfolio-readiness.v1.schema.json`; this spec deliberately does not restate
field lists beyond the contract-critical ones):

- `schema: "portfolio-readiness/v1"` — **versioned from day one.** Any breaking change
  bumps the version and both sides in the same change-set (the envelope-contract lesson:
  unversioned cross-repo shapes silently diverge into mutual unsatisfiability).
- `repo`, `generated`, per-check results (admission/advisory, status, details, `fix`),
- `admission_passed: bool`,
- `certified: false` + `certification` block (§6 — present from v1 so the seam exists),
- `remediation_queue: [...]` — one item per failed check that is repo-work (settings
  fixes appear as `fix` commands, not queue items, per Q5). Each item carries the
  check id, the target repo, the fix description, and enough machine detail for
  `factory create` to scaffold without re-deriving.

**Consumer contract:** `factory create --from-readiness <path>` (intent-packages)
reads the file, validates `schema == "portfolio-readiness/v1"` (fail closed on any
other value), groups the queue into ONE maintenance-remediation package (profile
already registered; routing row already exists), and scaffolds via the existing
staging-validate-move path in `scaffolds.py`. The consuming test's fixture is captured
from a **live kit run** during validation (Inc 3) — never hand-typed. factory reads the
kit's published schema by pointer (path documented in the flag's help text and the
fixture's provenance comment).

## 5. Entry point (amendment 2) — decided

**The passthrough embeds the documented invocation; project-standards gains no new
entry point.** Verified state: `[project.scripts] portfolio = "portfolio.cli:main"`
is already declared (`pyproject.toml:21-22`) and `.venv/bin/portfolio` exists and runs.
What is missing is only global PATH presence — and the fix for that is the caller's
job, not a new install surface. `factory onboard` therefore invokes:

    uv run --project "$PROJECT_STANDARDS_DIR" portfolio onboard <repo> [args…]

with `PROJECT_STANDARDS_DIR` defaulting to `~/Projects/project-standards`
(env-overridable, same pattern as the factory's other external-tool env vars).

Why this over a global console script: `uv run --project` resolves the already-declared
entry point deterministically even on a fresh checkout with no venv (uv syncs on
demand), requires no PATH mutation in Devon's shell or CI, and matches the established
factory pattern of shelling to sibling-repo CLIs with an explicit location. A global
install would be a new deployment artifact with an update story nobody owns — the
governance-map has no lane for it, and inventing one is out of scope here.

## 6. Certification seam — construction mode (ruling 2026-07-30)

The readiness result distinguishes **checks-pass** (`admission_passed`) from
**certified** (`certified`) from v1 — this schema distinction ships unchanged.
Certification's definition (decided): one harmless docs-only change driven through the
full factory path on the onboarded repo — proving caller, secrets, runner, PR, and
verification WORK, not merely exist.

**Construction-mode staging:** dispatch config for the canary is a setting to flip,
not a graduation event. When Inc 4 is reached: flip the change-class config, run the
canary, restore the config, note it in the closeout. The engineering rigor is kept in
full — the canary envelope is authored under the WS-6.4 dry-run rules (mutator proves
a diff on a clean current clone, ordered commands run twice, verifier last), and the
canary PR is merged by Devon (human merge is structural, not modal). Incs 1–3 build
the seam (`certified: false`, `certification: {method: "docs-canary/v1",
evidence: null}`), not the execution.

## 7. Increments

- **Inc 0 (done):** intent-packages PR #39 — decompose checkout-currency guard.
- **Inc 1 (project-standards):** `portfolio onboard` verb + check set + versioned
  readiness result + caller template asset + tests (every admission check proven to
  fire on a constructed failing instance). Own PR(s), repo-coherent.
- **Inc 2 (intent-packages):** `factory onboard` passthrough (§5) +
  `factory create --from-readiness` (§4). Fixture initially from a local kit run of
  Inc 1 on a constructed repo; refreshed from the live brain run in Inc 3. Own PR.
- **Inc 3 (validation, read-only on targets):** run the kit on change-manager (expect
  ~clean; any surprise is a finding, not a fix — report it) and brain (expect a real
  queue); `factory create --from-readiness` scaffolds brain's remediation package,
  validated, **stopping at Devon's gate** (not submitted without him); both readiness
  results retained as closeout evidence.
- **Inc 1b (factory-runner, one line):** the `RECOMMENDED_CALLER_PIN` file (§3
  check 6), initialized to the current recommended workflow SHA. Own tiny PR.
- **Inc 4 (last):** certification canary per §6 — flip the change-class config, run,
  restore, note in closeout. WS-6.4 dry-run rules apply to its envelope; Devon merges
  the canary PR.

**Workstream intake:** WS-P2.11's own intent package goes through `factory`
(create → validate → submit → Devon's /review gates) after this spec is approved and
before Inc-1 implementation — the factory's second real front-door use. Step 0's fix
makes the checkout-currency precondition automatic.

**Before any cross-repo mutation:** the portfolio-wide impact grep for every touched
contract surface (readiness schema string, `delivery_profile` frontmatter key, caller
workflow filename) COMPLETES first — per the closeout contract's HQ self-binding line.

## 8. Claim corrections to record at closeout

1. "Callers are SHA-pinned" (earlier HQ statement) → **5 of 6 callers are `@main`**;
   only change-manager is pinned (verified 2026-07-30). HQ has acknowledged; record in
   closeout as a claim correction.
2. The portfolio CLAUDE.md "scanner allowlist is cwd-anchored" invariant is stale —
   fixed 2026-07-04 (`security-standards` `cli.py:80`, regression-tested,
   unreproducible today), and backlog item `9c36be554dbb` exists nowhere in that repo.
   Propose retraction at closeout (doc edit is out-of-brief; propose, don't apply,
   unless HQ says otherwise).
3. factory-runner's stale plan-doc caller template (2 of 4 secrets) is the reason the
   kit template derives from the deployed change-manager caller, not the doc.

## 9. Risks / residuals (named honestly)

- The kit's pin check detects caller staleness; it cannot detect a workflow/CLI
  functional mismatch (the GAP-4 runner-side class) — that remains factory-runner's
  open P1 chain (no CI; pyright-red `make check`; guard). Residual, per S-B.
- `ci.executed` depends on `gh` log formats; the check must fail UNKNOWN-closed (not
  green) when the log is unreadable.
- Exit-criterion #2 residual: the kit existing ≠ five repos onboarded. Adoption is
  later work; closeout states it.
