---
name: project-standards
tier: active
status: active
purpose: 'PROJECT.md portfolio toolkit: scaffold, validate, capture, and aggregate
  dev-state + backlog across repos.'
version: 0.1.0
version_source: pyproject
updated: '2026-07-02'
foundation: true
foundation_contract: 1
applicable_standards:
  project: '1.0'
  security: '1.0'
  code: '1.1'
required_checks:
- id: quality
  executor: github-actions:quality.yml
- id: portfolio-scan
  executor: launchagent:com.devon.portfolio-scan
---

## Backlog

- [x] (P2) Onboard to code-standards (foundation matrix red: code.not-onboarded) — added 2026-07-02
- [x] (P1) Foundation conformance matrix — census keys, checker adapters, portfolio foundation CLI — added 2026-07-02 Plan: docs/superpowers/plans/2026-07-02-foundation-conformance-matrix.md

- [ ] (P2) CI guard: STANDARD_VERSION must be bumped when the standard's rules change in a diff (WS-1.3 follow-up; without it versioning rusts silently) — added 2026-07-03
- [x] (P3) Compliance bookkeeping now keys infra results, exception usage, and stale-exception attribution by resolved repository path; duplicate basenames under different roots cannot cross-assign state. — added 2026-07-03; resolved 2026-07-04
- [x] (P3) Burned the full-repo ruff debt to zero, formatted the repository, made pyright's Python version/source scope deterministic, and fixed the source type errors it exposed. Five intentionally complex boundary functions carry explicit local `C901` annotations rather than a hidden global baseline; test fixture lines ignore E501 only. Full `make check`: ruff + format + pyright clean, 227 tests pass. — added 2026-07-03; resolved 2026-07-04
- [ ] (P2) portfolio onboard's certification block has no evidence-recording affordance: certified stays false in the readiness JSON even after a canary run completes (WS-P2.11 canary evidence lives only in the orchestrator evidence pack and the closeout). Add a recorded-certification input (e.g. ~/.portfolio/certifications/<repo>.json written from canary evidence) that the kit surfaces in certification.evidence — added 2026-07-30
- [ ] (P3) Promote the July-2026 SDS campaign's real lessons (the CLAUDE.md invariant corpus in orchestrator/intent-packages/factory-runner + the ~/docs closeouts) into the brains via the governed WS-6.2 promotion loop, so the knowledge becomes queryable by any session. This is the content half that WS-P2.12's enrichment pipe (deferred 2026-07-30) waits on — the pipe's build trigger is a brain road with real content for a class the factory runs — added 2026-07-30
- [ ] (P2) portfolio onboard FAILS OPEN on a bad argument: given a bare repo name instead of a path it prints 'not a directory' and EXITS 0. The conformance kit — the tool whose job is to refuse non-conformant repos — attests rather than refuses on its own input error. A caller scripting it would read exit 0 as 'admission passed'. Found 2026-07-31 during WS-P2.22. Same defect class as the standing attestation P1, one level up: the checker itself. Fix: non-zero exit on an unusable argument — added 2026-07-31 — DOES NOT REPRODUCE, verified 2026-08-03: `portfolio onboard <bare-name>` and `portfolio onboard /nonexistent` both exit 2, via BOTH entrypoints (`python3 -m portfolio` and the installed `.venv/bin/portfolio` console script — checked separately because testing the module path when the console script is what ships is a known way to measure the wrong thing). `run()` has returned 2 on a non-directory since the original onboard commit 59bbf8a, so there is no window in which this was true for this argument. Left OPEN rather than closed because the capture presumably measured something real: if it was a different verb, a different invocation, or the exit code being swallowed by a wrapper, that is still a fail-open worth finding. Whoever reopens this: state the exact command measured.
- [ ] (P2) runner.caller reports 'violation' for a repo that is deliberately not a factory target, which converts an unmade scope decision into a standing defect and invites a future session to 'fix' it by adding a caller. Per ADR-0015 (orchestrator docs/decisions/0015): a repo should DECLARE whether it is a factory target — in PROJECT.md frontmatter alongside delivery_profile, which the kit already reads — and runner.caller should report 'not-applicable' with the declared reason for a non-target. The vocabulary already exists (matrix.py: pass|violation|unknown|not-applicable) and this is exactly the treatment repo.protection got in PR #14 for private repos on a plan without branch protection. Affects factory-runner and project-standards, both decided non-targets 2026-08-04. Until this ships, every estate sweep reports two runner.caller violations that are decisions rather than defects. — added 2026-08-04
## Future plans
