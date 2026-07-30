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
  code: '1.0'
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
## Future plans
