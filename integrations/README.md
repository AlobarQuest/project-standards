# Portfolio tools — usage reference

Operational wrappers around the `portfolio` CLI for maintaining the portfolio across
every repo under `~/Projects` and `~/Developer`. The source of truth for each project is
its **repo-root `PROJECT.md`** (frontmatter + `## Backlog`); the tools scaffold, capture,
and roll those up.

All four scripts live in `~/Projects/project-standards/integrations/` and are installed/
chmod'd by `install.sh`. Run them directly, e.g.:

```bash
~/Projects/project-standards/integrations/portfolio-scan.sh
```

---

## The tools at a glance

| Tool | What it does | Run it… |
|------|--------------|---------|
| `portfolio-scan.sh` | Refresh the rollup (`portfolio.json` + `PORTFOLIO.md`) | Daily 3am (auto) + anytime |
| `portfolio-triage.sh` | Place captured-but-unplaced inbox items into a repo | When the inbox has items |
| `portfolio-init.sh` | Onboard a repo — scaffold its `PROJECT.md` | When a new project is created |
| `portfolio-nudge.sh` | Stop-hook that warns if a session's repo lacks a manifest | Automatic (not run by hand) |

---

## `portfolio-scan.sh` — refresh the rollup

Regenerates the derived views from every project's `PROJECT.md`:
- `~/.portfolio/portfolio.json` — machine-readable
- `~/.portfolio/PORTFOLIO.md` — the digest: per-project table + unified backlog
- appends a timestamped summary line to `~/.portfolio/scan.log`

```bash
portfolio-scan.sh          # prints e.g. {"projects": 53, "fails": 9, "warns": 7}
```

- Runs automatically **every day at 03:00** via the `com.devon.portfolio-scan` LaunchAgent.
- `fails`/`warns` are the health signal. The steady-state baseline is the uncatalogued junk
  dirs (`missing_manifest`) + non-git parking stubs (`not_git`). Watch for *movement* off
  baseline: a new `missing_manifest` = a repo that needs `init`; a non-`missing_manifest`
  FAIL (e.g. `bad_yaml`) = a real manifest problem.
- Trigger an off-schedule run: `launchctl start com.devon.portfolio-scan`
- Watch history: `tail -f ~/.portfolio/scan.log`

## `portfolio-triage.sh` — clear the inbox

New backlog items are captured **inbox-first** (`~/.portfolio/inbox.jsonl`); items that
can't auto-place (ambiguous repo, or dirty tree) wait in the inbox. This walks them one at
a time:

```bash
portfolio-triage.sh
# For each item:  → assign to repo (name / path / [s]kip / [q]uit):
```

- Type a **repo name** (`brain` → resolves to `~/Projects/brain` or `~/Developer/brain`),
  a **full path**, `s` to leave it in the inbox, or `q` to stop.
- Assigning writes the item into that repo's `PROJECT.md` `## Backlog` and marks it triaged.
- Auto-runs `scan` afterward so the rollup reflects the new items.
- Empty inbox → says so and exits.

## `portfolio-init.sh` — onboard a repo

Scaffolds a repo-root `PROJECT.md`. Idempotent, **never runs `git init`**, **never clobbers
human-written fields** (fills only blanks).

```bash
portfolio-init.sh                       # current dir, active tier
portfolio-init.sh /path/to/repo         # a specific repo
portfolio-init.sh --parking             # long-tail/experiment (minimal manifest)
portfolio-init.sh --purpose "does X"    # non-interactive (for automation)
```

- Defaults to the **current directory** and the **active** tier.
- Auto-detects `version`/`version_source` and the `purpose` (README first line). If purpose
  is undetectable it **prompts** for a one-liner — unless `--purpose` is given or there's no
  TTY (then it leaves a `TODO` and warns).
- `--purpose` fills the field only when it's blank/placeholder, so it won't overwrite an
  existing purpose.
- Shows the resulting manifest + a `lint` check. Commit `PROJECT.md` as part of your normal
  flow; the daily scan picks it up regardless.

## `portfolio-nudge.sh` — session Stop hook (automatic)

Registered as a Stop hook in `~/.claude/settings.json`. At the end of a session, if the
session's git repo has a missing or invalid `PROJECT.md`, it prints a non-blocking nudge.
Not run by hand.

---

## Maintenance rhythm

Assuming build agents manage their own backlogs (capture/check-off via `portfolio add` /
the `backlog` skill), the recurring human tasks are just:

```bash
portfolio-scan.sh        # refresh the picture (also runs daily 3am)
open ~/.portfolio/PORTFOLIO.md
portfolio-triage.sh      # place any stray inbox captures
```

…and `portfolio-init.sh` whenever a new repo appears (the scan flags it as a FAIL).

---

## Where `init` fits in the project lifecycle

| Hook point | How | Trade-off |
|---|---|---|
| **Project scaffolding step** (`project-initiation` skill / template) | Call `portfolio-init.sh --purpose "<scoped purpose>"` right after the repo is created | Best — non-interactive, purpose already exists from scoping, manifest is born complete |
| **First commit / pre-commit** | Init if `PROJECT.md` missing | Catches anything that skipped scaffolding |
| **Manual, on `git init`** | Run it when starting a repo | Simple, but relies on memory |
| **Nothing — let scan catch it** | Daily 3am scan FAILs new repos as `missing_manifest` | Zero effort, but a lag; you circle back later |

The scan is a safety net (new repos surface as FAILs), so where you place `init` is about
*reducing that lag*, not plugging a hole.

---

## Concepts & file locations

- **Tier** — `active` (full manifest: name/tier/status/version/version_source/purpose/updated)
  vs `parking` (name/tier/status/purpose only, for long-tail/experiments).
- **Inbox vs backlog** — *inbox* = captured but not yet written into a repo (held when the
  target was ambiguous/dirty); *backlog* = items that have landed in a repo's `PROJECT.md`,
  which `scan` rolls up.
- **Source of truth** — each repo's `PROJECT.md` (committed, travels with the repo).
- **Derived (never committed, regenerated each scan):** `~/.portfolio/portfolio.json`,
  `~/.portfolio/PORTFOLIO.md`.
- **Inbox store:** `~/.portfolio/inbox.jsonl` · **Scan log:** `~/.portfolio/scan.log`
- **Schedule:** `~/Library/LaunchAgents/com.devon.portfolio-scan.plist` (daily 03:00).

## Underlying CLI

The scripts wrap this; use it directly for anything they don't cover:

```bash
PYTHONPATH="$HOME/Projects/project-standards/src" python3 -m portfolio <cmd>
#   init <repo> [--tier active|parking]   lint <repo>   add "<text>" [--repo R] [--priority P1|P2|P3]
#   triage [--assign <id> --repo <R>]      scan [--roots ...]
#   query [--tier T --status S --stale --has-backlog --tag T]
```
