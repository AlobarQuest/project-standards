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
- [ ] (P3) compliance rows key by repo basename — two same-named repos under different roots (~/Projects/x vs ~/Developer/x) would cross-assign infra cells and stale-exception attribution; key by path — added 2026-07-03
- [ ] (P3) Burn down the full-repo ruff baseline (166 errors, red on main) or make make check baseline-aware — the CLAUDE.md 'make check must be green' gate is currently untruthful; enforced gate today is diff-scoped only — added 2026-07-03
## Future plans
