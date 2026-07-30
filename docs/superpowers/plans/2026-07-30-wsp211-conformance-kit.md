# WS-P2.11 Conformance Kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-command repo onboarding (`portfolio onboard <repo>`) that emits a versioned
machine-readable readiness result whose failed checks form a remediation queue consumable by
`factory create`, plus the owned caller template and declared-pin story.

**Architecture:** New `onboard` verb in project-standards composing existing checkers plus five
new checks; readiness result schema `portfolio-readiness/v1` published in this repo; thin
`factory onboard` passthrough and `factory create --from-readiness` consumer in intent-packages;
one-line `RECOMMENDED_CALLER_PIN` declaration in factory-runner.

**Tech Stack:** Python 3.12, argparse (existing CLI pattern), pytest, `gh` CLI for remote reads,
uv for cross-repo invocation.

**Spec:** `docs/superpowers/specs/2026-07-30-wsp211-conformance-kit-spec.md` (APPROVED, construction-mode amended). The spec's decisions register, check definitions (§3), schema contract (§4), and staging (§7) govern; this plan implements them.

## Global Constraints

- Construction mode (`~/docs/…/2026-07-30-construction-mode-ruling.md`): rigor not ritual — collected counts never check colors; guards proven to FIRE; pointers not shapes; fixtures from live sources; clean trees; Devon merges.
- The kit is READ-ONLY against target repos and GitHub settings. It writes only stdout/stderr and `~/.portfolio/readiness/<repo>.json`.
- Nothing mints orchestrator work units. No orchestrator changes at all.
- Schema string is exactly `portfolio-readiness/v1`; any breaking change bumps it and both sides in one change-set.
- Every admission check ships a test constructing a FAILING instance (guard proven to fire).
- Increments land repo-coherently: no PR mixes repos. Kit (Inc 1) lands before consumer (Inc 2); consumer fixture refreshed from a live run (Inc 3).
- Env overrides follow `config.py`'s established `os.environ.get` pattern; all new paths/locations env-overridable for tests.
- Per-task gates: `ruff check`, `ruff format`, targeted pytest; full `make check` (with collected count read) before each PR.

---

## Increment 1 — project-standards: the kit (Tasks 1–8, one PR)

Branch: `feat/wsp211-onboard-kit` off current `main` (`8d12eee`).

### Task 1: Readiness schema module + published JSON schema

**Files:**
- Create: `src/portfolio/readiness_schema.py`
- Create: `schema/portfolio-readiness.v1.schema.json`
- Test: `tests/test_readiness_schema.py`

**Interfaces:**
- Produces: `SCHEMA_VERSION = "portfolio-readiness/v1"`; `build_result(repo_name, checks, generated) -> dict`; `remediation_item(check_id, repo, fix, detail) -> dict`; `AdmissionCheck`/`AdvisoryCheck` classification constants `ADMISSION_CHECKS`, `ADVISORY_CHECKS` (ordered tuples of check ids: `git.current`, `project.manifest`, `code.onboarded`, `ci.executed`, `security.clean`, `runner.caller`, `profile.declared`; advisory: `deps.dependabot`, `repo.protection`, `backlog.hygiene`, `standards.pinned`).
- Consumes: `matrix.CheckResult` (existing dataclass) — each check result is carried as `{id, status, details, fix}`.

- [ ] **Step 1: Write the failing tests** — `build_result` emits `schema == "portfolio-readiness/v1"`, `admission_passed` false when any admission check is not `pass`, `certified` false with `certification == {"method": "docs-canary/v1", "evidence": None}`, `remediation_queue` contains one item per failed admission check that carries a `remediation` payload (and none for advisory/settings-only failures); the emitted document validates against `schema/portfolio-readiness.v1.schema.json` (use `json.load` + a minimal structural assert on `required` keys — do not add a jsonschema dependency).
- [ ] **Step 2: Run tests, verify FAIL** (`.venv/bin/pytest tests/test_readiness_schema.py -q` → import error).
- [ ] **Step 3: Implement** `readiness_schema.py`: constants, `build_result` assembling the §4 shape from a list of per-check dicts `{id, status, details, fix, remediation | None}`; write the JSON-schema file describing top-level required keys (`schema`, `repo`, `generated`, `checks`, `admission_passed`, `certified`, `certification`, `remediation_queue`).
- [ ] **Step 4: Run tests, verify PASS.**
- [ ] **Step 5: Commit** `feat(onboard): readiness result schema portfolio-readiness/v1`.

### Task 2: `git.current` check

**Files:** Create: `src/portfolio/onboard_checks.py`; Test: `tests/test_onboard_checks_git.py`

**Interfaces:**
- Produces: `check_git_current(repo: Path) -> dict` returning `{id: "git.current", status, details, fix}` (status uses `matrix.PASS/VIOLATION/UNKNOWN` strings).
- Consumes: `checkers._run` (existing subprocess helper).

- [ ] **Step 1: Failing tests** — four constructed instances using tmp git repos with a `file://` origin (mirror intent-packages `tests/factory/test_validations.py::_checkout_with_origin` construction): (a) current+clean → pass; (b) origin advanced → violation, `fix` contains `pull --ff-only origin main`; (c) dirty worktree → violation; (d) no origin → violation (fetch failure), never unknown-green.
- [ ] **Step 2: Verify FAIL.**
- [ ] **Step 3: Implement** — `git fetch origin main` → on failure VIOLATION with fetch error in details; `rev-parse HEAD` vs `rev-parse origin/main`; `status --porcelain` empty. Fix strings name exact commands with the repo path interpolated.
- [ ] **Step 4: Verify PASS.** **Step 5: Commit** `feat(onboard): git.current admission check`.

### Task 3: `code.onboarded` + `ci.executed` checks

**Files:** Modify: `src/portfolio/onboard_checks.py`; Test: `tests/test_onboard_checks_ci.py`

**Interfaces:**
- Produces: `check_code_onboarded(repo) -> dict`; `check_ci_executed(repo, gh=_gh) -> dict`; module-level `_gh(args: list[str]) -> str | None` helper (returns stdout or None on failure) — injectable for tests.
- Consumes: nothing new; `gh run list/view` CLI at runtime.

- [ ] **Step 1: Failing tests** — code.onboarded: missing `.code-standards.toml` → violation (fix: `code-standards init`); missing `.github/workflows/quality.yml` → violation (fix: `code-standards sync`); both present → pass. ci.executed (inject fake `gh`): (a) run success + log containing `collected 227 items` → pass, details carry the count; (b) run success + log with `collected 0 items` → violation; (c) run success + no collected line (tools skipped) → violation with fix naming the green-having-run-nothing trap; (d) gh failure/no runs → **unknown status, admission-failing** (assert `build_result` from Task 1 treats unknown admission as not passed — UNKNOWN never reads as green).
- [ ] **Step 2: Verify FAIL.** **Step 3: Implement** (repo slug from `git remote get-url origin`, parse `github.com[:/]owner/repo`; `gh run list --workflow quality.yml --branch main --limit 1 --json databaseId,conclusion`; `gh run view <id> --log` grepped for `collected (\d+) items?`). **Step 4: Verify PASS.** **Step 5: Commit** `feat(onboard): code.onboarded + ci.executed checks (collected counts, never colors)`.

### Task 4: `security.clean` + `profile.declared` checks

**Files:** Modify: `src/portfolio/onboard_checks.py`, `src/portfolio/config.py` (add `intent_packages_dir()` env override `INTENT_PACKAGES_DIR` default `~/Projects/intent-packages`; `factory_runner_slug()` default `AlobarQuest/factory-runner`); Test: `tests/test_onboard_checks_profile.py`

**Interfaces:**
- Produces: `check_security_clean(repo) -> dict` (wraps existing `checkers.check_security`, then if the repo references BWS UUIDs adds `.bws-secrets.toml`-present and governance-map-consumer-entry subchecks); `check_profile_declared(repo, registered_profiles) -> dict`; `registered_profiles()` reading intent-packages' `PROFILES` keys via `uv run --project <dir> python -c "from intent_packages.profiles import PROFILES; print('\n'.join(sorted(PROFILES)))"` — pointer, never a copied list.
- Consumes: `checkers.check_security`; security-standards path via existing `config.standards_repos()` pattern; `manifest.parse_frontmatter` for the `delivery_profile` key.

- [ ] **Step 1: Failing tests** — security: BLOCK>0 → violation (reuse the existing checker's env-based fake-scanner test pattern from `tests/` conftest `standards_env`); BWS-referencing repo without `.bws-secrets.toml` → violation with fix `python -m security_scan.genmanifest <repo> --write`; without governance entry → violation with fix naming the `[[repo]]` addition. profile: frontmatter missing `delivery_profile` → violation (fix names the key and the registered names); unknown name → violation; registered name → pass. `registered_profiles` is injected in tests (constructed list) — plus one test that the live subprocess path parses `PROFILES` output lines (monkeypatched `_run` returning canned stdout).
- [ ] **Step 2: Verify FAIL.** **Step 3: Implement.** **Step 4: Verify PASS.** **Step 5: Commit** `feat(onboard): security.clean + profile.declared checks`.

### Task 5: `runner.caller` check + caller template asset

**Files:** Modify: `src/portfolio/onboard_checks.py`; Create: `src/portfolio/templates/factory-runner-caller.yml`; Test: `tests/test_onboard_checks_runner.py`

**Interfaces:**
- Produces: `check_runner_caller(repo, gh=_gh) -> dict`; `declared_pin(gh=_gh) -> str | None` (reads `RECOMMENDED_CALLER_PIN` via `gh api repos/<slug>/contents/RECOMMENDED_CALLER_PIN --jq .content` base64-decoded, stripped); `required_secrets(sha, gh=_gh) -> set[str] | None` (reads `.github/workflows/factory-runner.yml` at that SHA, parses the `secrets:` keys marked `required: true`); template with `{{FACTORY_RUNNER_WORKFLOW_SHA}}` slot, content mirroring change-manager's deployed caller (27 lines: `workflow_dispatch.inputs.work_unit_id`, permissions block `contents: write / pull-requests: write / actions: read / checks: read`, `uses:` slot, `with: {work_unit_id, orchestrator_url: https://sds.alobar.net}`, four `secrets:` passthroughs).
- Consumes: config `factory_runner_slug()` from Task 4.

- [ ] **Step 1: Failing tests** (inject fake `gh`): (a) no caller file → violation, fix points at the template path + fill instruction; (b) `uses: …@main` → violation naming the GAP-4 class; (c) full-SHA pin ≠ declared pin → violation "behind the declared pin"; (d) pin matches but a required secret absent from `gh secret list` output → violation naming the missing secret; (e) all good → pass; (f) declared-pin fetch fails → unknown (admission-failing). Secrets set in tests comes from a canned workflow YAML fixture captured from the real reusable workflow (fixtures from live sources — capture in Step 0 of this task via `gh api`), never typed from memory.
- [ ] **Step 2: Verify FAIL.** **Step 3: Implement.** **Step 4: Verify PASS.** **Step 5: Commit** `feat(onboard): runner.caller check (declared pin) + owned caller template`.

### Task 6: Advisory checks

**Files:** Modify: `src/portfolio/onboard_checks.py`; Test: `tests/test_onboard_checks_advisory.py`

**Interfaces:**
- Produces: `check_dependabot(repo)`, `check_protection(repo, gh=_gh)` (branch protection on main, report-only), `check_backlog_hygiene(repo)` (reuse `validator.lint` WARN `aged_item`s), `check_standards_pinned(repo)` (reuse `compliance` version-drift synthesis for the declared standards).
- Consumes: existing `validator.lint`, `compliance` helpers.

- [ ] **Step 1: Failing tests** (one failing + one passing instance each; protection via injected gh). **Step 2–4: red → implement → green.** **Step 5: Commit** `feat(onboard): advisory checks`.

### Task 7: `onboard` orchestrator + CLI verb + digest

**Files:** Create: `src/portfolio/onboard.py`; Modify: `src/portfolio/cli.py` (new subparser + dispatch, same pattern as `foundation`); Test: `tests/test_onboard_cli.py`

**Interfaces:**
- Produces: `onboard.run(repo: Path, gh=_gh, registered_profiles=None, out_dir=None) -> dict` (the full result), CLI `portfolio onboard <repo>` printing JSON to stdout, digest to stderr, writing `~/.portfolio/readiness/<name>.json` (dir via `config` env override `PORTFOLIO_HOME`, existing pattern); exit 0 all-admission-pass / 1 admission failure / 2 internal error.
- Consumes: every check from Tasks 2–6, `readiness_schema.build_result` from Task 1.

- [ ] **Step 1: Failing tests** — CliRunner-style through `cli.main(["onboard", str(repo)])` (test through the entrypoint, per standing lesson): exit codes 0/1/2; stdout parses as JSON matching the schema; result file written under `PORTFOLIO_HOME`; digest names the next action for each failure; a fully-green constructed repo (all checks injected pass) yields `admission_passed: true, certified: false` and an empty queue; digest states certification is a separate gated step.
- [ ] **Step 2: Verify FAIL.** **Step 3: Implement** (checks run in the ADMISSION_CHECKS order then advisory; each wrapped so an exception → UNKNOWN + exit 2 path only for infrastructure errors of the kit itself). **Step 4: Verify PASS.** **Step 5: Commit** `feat(onboard): portfolio onboard verb + readiness digest`.

### Task 8: Inc-1 gate + PR

- [ ] `make check` on the committed tree; read the collected count (expect prior 227 + new tests, all pass; ruff + pyright clean).
- [ ] Commit spec + plan docs (`docs/superpowers/specs/…`, `docs/superpowers/plans/…`) as their own commit on the branch.
- [ ] `/code-review` the branch diff; fix findings; re-gate.
- [ ] Push, open PR "WS-P2.11 Inc 1: portfolio onboard conformance kit" — Devon merges.

## Increment 1b — factory-runner: declared pin (one PR)

- [ ] Impact grep COMPLETES first: `grep -rn "RECOMMENDED_CALLER_PIN" ~/Projects ~/Developer` (expect only kit + this file).
- [ ] Determine the recommended SHA: current factory-runner `origin/main` HEAD; verify the reusable workflow at that SHA declares the four required secrets (`gh api …/contents/.github/workflows/factory-runner.yml?ref=<sha>`).
- [ ] Branch `feat/recommended-caller-pin`; create `RECOMMENDED_CALLER_PIN` (single line: the full SHA, newline-terminated); README one-liner under the rollout doc pointing at it (two files max).
- [ ] PR — Devon merges. (No CI exists there; verification is the kit's Task-5 live read in Inc 3.)

## Increment 2 — intent-packages: passthrough + consumer (one PR)

Branch: `feat/wsp211-factory-onboard`.

### Task 9: `factory onboard` passthrough

**Files:** Modify: `src/intent_packages/factory_cli.py`; Test: `tests/factory/test_factory_cli.py` (extend)

**Interfaces:**
- Produces: `factory onboard <repo> [--json]` → `subprocess.run(["uv", "run", "--project", os.environ.get("PROJECT_STANDARDS_DIR", str(Path.home()/"Projects/project-standards")), "portfolio", "onboard", repo])`, exit code passed through verbatim.
- [ ] Failing test (monkeypatched subprocess capturing argv + injected returncode; asserts exact argv shape and passthrough of exit code) → red → implement → green → commit.

### Task 10: `factory create --from-readiness`

**Files:** Modify: `src/intent_packages/factory/scaffolds.py`, `src/intent_packages/factory_cli.py`; Test: `tests/factory/test_scaffolds_from_readiness.py`; Fixture: `tests/fixtures/readiness/brain.v1.json` (placeholder from a local Inc-1 kit run on a constructed repo; REPLACED by the live brain capture in Inc 3 — the fixture file carries a provenance comment naming the producing command).

**Interfaces:**
- Produces: `create(..., from_readiness: Path | None)` — reads the file; hard-fails unless `schema == "portfolio-readiness/v1"` (exact string, fail closed with the seen value in the error); refuses an empty `remediation_queue`; groups all queue items into ONE package scaffold on the `maintenance-remediation` profile, one acceptance-criterion stub per queue item carrying the item's check id and fix text; existing staging-validate-move path unchanged.
- [ ] Failing tests: wrong schema string → clean error naming both strings; empty queue → refusal; happy path scaffolds a package that `validate_package` accepts, with one AC per queue item. Red → implement → green → gate (`make check`, collected count) → PR — Devon merges.

## Increment 3 — validation (read-only on targets)

- [ ] Impact grep COMPLETES before any run that new consumers might read: `grep -rn "portfolio-readiness\|delivery_profile" ~/Projects ~/Developer` — inventory consumers, expect only this workstream's.
- [ ] Run `portfolio onboard ~/Projects/change-manager` — expect ~clean (surprises are findings to report, not fixes).
- [ ] Run `portfolio onboard ~/Projects/brain` — expect a real queue (stale `@main` caller at minimum).
- [ ] Capture both results to `~/docs/software-delivery-system/wsp211-validation/` as closeout evidence; refresh the Task-10 fixture from the live brain result and commit the refresh in intent-packages.
- [ ] `factory create --from-readiness <brain result>` → validated Draft package → STOP at Devon's gate.

## Increment 4 — certification canary (last)

- [ ] Flip the dispatch change-class setting to admit the docs-only class; author the canary envelope under WS-6.4 dry-run rules (mutator proves a diff on a clean current clone; ordered commands run twice; verifier last); run the canary on the onboarded repo; Devon merges the canary PR; restore the config; record the flip + run in the closeout.
- [ ] Mark the target repo's readiness `certification` block per the run's evidence (kit re-run).

## Self-review notes

- Spec §3 checks 1–7 → Tasks 2 (1), 2/7 composition (2 via existing `check_project` wrapped as `project.manifest` in Task 7's orchestrator — NOTE: implement the wrapper in Task 7, it is composition not a new check), 3 (3,4), 4 (5,7), 5 (6); advisory → Task 6. Schema §4 → Task 1 + Task 10. §5 → Task 9. §6 → Task 1 (seam) + Inc 4. §7 ordering → increment order above. §8 corrections + §9 residuals → closeout.
- Types: check functions all return the same `{id, status, details, fix}` dict shape consumed by `build_result`; statuses are `matrix` strings.
