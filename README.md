# project-standards

Every project carries a repo-root `PROJECT.md` (source of truth for its dev-state + backlog).
The `portfolio` CLI scaffolds, validates, captures, and aggregates.

## PROJECT.md schema
Frontmatter (active requires all; parking requires name/tier/status/purpose):

| field | values |
|-------|--------|
| name | string |
| tier | active \| parking |
| status | idea \| in-progress \| active \| archived |
| version | string \| n/a |
| version_source | package.json \| pyproject \| cargo \| git-tag \| none |
| purpose | one line |
| updated | YYYY-MM-DD |
| links | optional map (specs, roadmap) |

Body: `## Backlog` (lines `- [ ] (P#) text — added YYYY-MM-DD`) + `## Future plans`.

## CLI
`PYTHONPATH="$HOME/Projects/project-standards/src" python3 -m portfolio <cmd>` —
`init <repo>`, `lint <repo>`, `add "<text>"`, `triage`, `scan`, `query`.

## Install integrations
`bash integrations/install.sh` (then register the Stop hook in `~/.claude/settings.json`).
