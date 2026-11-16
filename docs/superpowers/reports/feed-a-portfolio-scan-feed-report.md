Outcome: done

# Report: feed-a-portfolio-scan-feed

- **PR:** [AlobarQuest/project-standards#63](https://github.com/AlobarQuest/project-standards/pull/63). It's ready for review, not a draft, and isn't merged.
- **Branch:** `hq/feed-a-portfolio-scan-feed`, based on `origin/main` `90391362e8bc68fac9637f830b885c26cea5087d`.
- **Content commits:**
  - `1657eb45610ed915bec7064219f6b1065336c091`: the feed, its wiring, the tests, and the conftest floor.
  - `45dc46e`: a test that pins the conftest floor.
  - `3f56ecfcf582ab552adb1128819151df22333a20`: mode `0644` and fsync, from the code review.
  - `980bce2e0bbecdca4ccc4cac564825fe64765275`: the members test spells out the four ids. This is the last content commit.
- **Head:** the commit that updates this report, directly on top of `980bce2e`.

## What I built

The 03:00 portfolio scan now writes `portfolio-feed.json` in the portfolio home, beside `portfolio.json` (ADR-0059 Amendment 11, decision item 1). The code changes are the following:

- **`src/portfolio/config.py`:** adds `feed_path()`, which returns `portfolio_home() / "portfolio-feed.json"`. It follows `PORTFOLIO_HOME` the way `json_path()` does.
- **`src/portfolio/feed.py`:** a new module.
  - `FEED_SCHEMA = "portfolio-feed.v1"`.
  - `FEED_CHECKS`: one named tuple of the four ids. A comment names its source, the orchestrator's `CAPABILITY_CHECKS` and `PERMISSION_CHECKS` in `src/work_carrier/workability.py`.
  - `format_scanned_at`: refuses a naive time, converts to UTC, and writes `YYYY-MM-DDTHH:MM:SSZ`.
  - `build_feed`: pure. It returns the exact bytes, as JSON with `indent=2` and `sort_keys=True`, a trailing newline, and repositories sorted by key.
  - `write_feed`: atomic, as the following section describes.
- **`src/portfolio/scan.py`:**
  - `scan()` takes a new `clock` parameter. Its default, `_utc_now`, returns `datetime.now(UTC)`. The scan calls it once, first, before anything is measured.
  - The existing naive `now` still feeds compliance and nothing else.
  - `_attach_factory` also returns the sweep's `by_path`, and the feed is built from that.
  - The feed is written last, after `portfolio.json` and `PORTFOLIO.md`.
  - `portfolio.json` and the digest are byte-for-byte unchanged in shape.
- **`tests/conftest.py`:** a new autouse fixture points `PORTFOLIO_HOME` at a per-test temporary directory. A test that doesn't ask for `portfolio_env` therefore still can't write `~/.portfolio`.
- **`tests/test_feed.py`:** 13 tests.

### How each repository's slug is obtained

The feed reads the slug a second time with `onboard_checks.repo_slug(Path(key))` for each key of the sweep's result. I didn't change the sweep's return shape, because every injected fake sweep returns path-keyed results. The feed keeps a key only when that slug, lowercased, is in the same `granted` set the sweep filtered on. The set of repositories is therefore the sweep's keys narrowed by membership, and the feed never walks the roots a second time.

A key gets no row in the following two cases. The real sweep can't produce either one, because it measured that path for a member slug moments earlier.

- `repo_slug` returns `None`: the origin is gone, or it isn't on GitHub.
- The slug names no member.

### Two working copies with one origin

The repository gets one row. A check keeps its status only when every copy agrees on it. A check the copies disagree on is left out of `checks`, and the reader treats it as UNKNOWN, so a disagreement fails closed. Only `runner.caller` could differ between copies, and since 2026-09-12 it reads the remote too. The copies can still differ when one transient read fails, because the sweep's memoizers don't cache failures.

### Atomic write

`write_feed` takes the following steps:

1. Calls `tempfile.mkstemp` in the feed's own directory.
2. Writes the text, flushes it, and calls `os.fsync`.
3. Sets mode `0644`, because `mkstemp` creates `0600` and the feed holds no secret.
4. Calls `os.replace` to move the temporary file onto `portfolio-feed.json`.

On any failure the function removes the temporary file and re-raises. An exception from `scan()` reaches `python -m portfolio scan` uncaught. `cli.py` maps only the normal return to 0 or 3, so an uncaught exception exits 1. The launcher logs `FAIL(rc=1)`, exits 1, and pings `/fail`. I didn't change the launcher or its exit-code meanings.

## Feed path and example document

The path is `$PORTFOLIO_HOME/portfolio-feed.json`, which defaults to `~/.portfolio/portfolio-feed.json`. The following example uses placeholder slugs and was produced by `build_feed`:

```json
{
  "member_record_unreadable": null,
  "repositories": [
    {
      "checks": {
        "factory.landing_known": "pass",
        "factory.pat_access": "pass",
        "factory.secrets": "pass",
        "runner.caller": "pass"
      },
      "repository": "example-owner/repo-a"
    },
    {
      "checks": {
        "factory.pat_access": "violation",
        "runner.caller": "violation"
      },
      "repository": "example-owner/repo-b"
    }
  ],
  "scanned_at": "2026-11-17T08:00:35Z",
  "schema": "portfolio-feed.v1"
}
```

The sweep for `repo-a` returned all six checks. The feed drops `factory.pat_scope` and `factory.app_access`. The sweep for `repo-b` recorded only two of the four, so the other two are absent.

When the member record is unreadable, the feed has `"repositories": []` and `"member_record_unreadable"` holds the same reason string as `portfolio.json`. For example: `"the orchestrator answered 401 for GET /api/v1/members"`.

## Tests and checks

- **`make check`:** `collected 798 items`, `798 passed`. Ruff reports "All checks passed", and Pyright reports 0 errors and 0 warnings. The branch adds 13 tests, all in `tests/test_feed.py`. Measured at `980bce2e`.
- **Security scan** (`security_scan.cli . --category security`, from the worktree root): 0 BLOCK, 2 WARN, and 1 INFO.
  - The 2 WARN findings are `bws.manifest-matches-usage`, for two UUIDs in `src/portfolio/sds_guidance.py`. That file is identical on `origin/main` and untouched by this diff.
  - The INFO finding is the judgment-only `bws.least-privilege-scope`.
- **Real-home isolation:**
  - Every test that calls the portfolio `scan()` asks for `portfolio_env`. The other `scan` hits are `retired_hosts.scan`, and `test_wiring.py` only mentions `bws-scan-gate.sh`. The launcher test sets `HOME` to a temporary directory.
  - The new autouse fixture is the floor under any future test, and `test_no_test_sees_the_real_portfolio_home` pins it.
  - `ls ~/.portfolio/portfolio-feed.json` reported "No such file" before the first test run and again after each full suite.
- **`/code-review` (medium) on `origin/main...HEAD`:** 6 findings.
  - **Fixed:** the `0600` mode and the missing fsync (`3f56ecfc`).
  - **Not a bug:** `granted` isn't normalized. `member_scope` already lowercases every slug, and the sweep uses the same comparison.
  - **Kept as the handoff specifies:** the second `repo_slug` read, which the handoff allows, and writing the feed after `portfolio.json` and the digest, which the handoff requires.
  - **Kept by choice:** dropping disagreeing checks, which fails closed, and the `(count, by_path)` tuple, a small private helper.

### Mutants

I ran all 18 mutants at the final content commit `980bce2e`. I applied each one alone to committed content, ran `tests/test_feed.py`, and restored with `git checkout -- <file>`. Every mutant went red, and `git status` was clean afterwards.

| # | Mutant | Red test or tests |
|---|---|---|
| M1 | Drop the member filter (`slug is None` only) | `test_a_sweep_key_whose_origin_names_no_member_gets_no_row` |
| M2 | Key not lowercased | `..._members_only_with_full_keys_and_four_ids`, `test_two_working_copies_...` |
| M3 | Keep every check id, not only the four | `..._members_only_with_full_keys_and_four_ids` |
| M4 | Repositories unsorted | `test_the_same_inputs_write_the_same_bytes` |
| M5 | `isoformat()`, which gives `+00:00` and microseconds | `test_scanned_at_is_the_injected_instant_in_utc_whole_seconds` |
| M6 | No UTC conversion | `test_scanned_at_is_..._utc_whole_seconds` |
| M7 | Naive time accepted | `test_a_naive_scan_time_is_refused` |
| M8 | Write error swallowed (no re-raise) | `test_a_failed_write_raises_...`, `test_a_failed_first_write_leaves_no_feed` |
| M9 | Temporary file left behind on failure | same two |
| M10 | Duplicate copies keep the first copy's statuses | `test_two_working_copies_...` |
| M11 | Unreadable reason not passed to the feed | `test_an_unreadable_member_record_gives_no_rows_and_says_why` |
| M12 | One feed id renamed (`factory.landing`) | `..._four_ids`, `test_every_feed_check_is_one_the_sweep_can_emit` |
| M13 | Feed written before `portfolio.json` | `test_a_failed_write_raises_...`, `test_a_failed_first_write_leaves_no_feed` |
| M14 | Conftest floor removed | `test_no_test_sees_the_real_portfolio_home` |
| M15 | Clock ignored (`datetime.now(UTC)` in place of `clock()`) | `test_scanned_at_is_..._utc_whole_seconds` |
| M16 | `chmod` to `0644` removed | `test_the_same_inputs_write_the_same_bytes` (mode assertion) |
| M17 | A fifth id (`factory.pat_scope`) added to `FEED_CHECKS` | `..._four_ids` |
| M18 | One id (`factory.pat_access`) removed from `FEED_CHECKS` | `..._four_ids` |

## Files changed

- `src/portfolio/config.py`
- `src/portfolio/feed.py` (new)
- `src/portfolio/scan.py`
- `tests/conftest.py`
- `tests/test_feed.py` (new)
- `docs/superpowers/reports/feed-a-portfolio-scan-feed-report.md` (this report)

## Self-review

- The feed is a separate, pure builder plus a writer. `scan()` gained one parameter and three lines, and `portfolio.json` and the digest are untouched.
- No owner name appears in code, and the tests use placeholder owners.
- The feed holds statuses only. A test plants a marker in `details`, `fix`, and `remediation`, and asserts that the marker is absent from the feed's bytes.
- **TDD order:** I drafted `feed.py` before its tests, not test-first. To compensate, I proved every rule red with the 18 mutants in the preceding table.

## Concerns

- **The feed's time and `portfolio.json` can disagree after a failure.** If the feed write fails, `portfolio.json` and the digest are already new while the feed still holds the previous scan. That order is the one the handoff specifies. The previous feed has its own older `scanned_at`, so the reader ages it correctly, and the run pings `/fail`.
- **The second slug read is a little racy.** The feed reads `git remote get-url origin` a second time per measured repository. If an origin changes between the sweep and the feed, which takes milliseconds, the feed keys the row by the new origin, and only if that origin is still a member. This costs one extra `git` subprocess per member, about eight per night.

- **A sweep key can be left out without a trace.** When the second `repo_slug` read returns `None`, or returns a slug that names no member, the feed leaves that key out and logs nothing. The handoff doesn't cover this case. The real sweep can't produce it except in the race in the preceding item. The reader holds a record with no row, so this fails closed.

## For the next steps

The following is the contract the nightly (security-standards) and the carrier's reader (orchestrator) can rely on:

- **Path:** `~/.portfolio/portfolio-feed.json`, written by the scan's launch agent as the operator user, mode `0644`. The scan replaces it atomically with `os.replace`, so a reader sees the old file or the new one, never a partial one.
- **`schema`:** the string `"portfolio-feed.v1"`. Refuse any other value. A future shape change gets a new string.
- **`scanned_at`:** a UTC string matching `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`, in whole seconds with a literal `Z`. It's taken once when the scan starts, before anything is measured. Copy it verbatim into `timestamp` and `source.ref`. A re-run of the nightly on the same feed sees the same `scanned_at` and therefore derives the same `event_id`.
- **`member_record_unreadable`:**
  - `null` when the member record was read.
  - Otherwise a reason string. In that case `repositories` is always `[]`.
  - The nightly needs this to choose `result` and the field that marks "measured nothing", which Amendment 11 decision item 2 leaves to the code step.
- **`repositories`:** a list sorted by `repository`. Each item has exactly two keys:
  - `repository`: a full lowercased `owner/repo`. At most one row exists per repository.
  - `checks`: an object whose keys are a subset of `runner.caller`, `factory.secrets`, `factory.landing_known`, and `factory.pat_access`. Each value is the status string the sweep recorded, one of the values in `portfolio.matrix`. `factory_checks.py` uses neither `accepted-exception` nor `not-applicable`. `onboard_checks.py`, which holds `runner.caller`, uses `not-applicable` and not `accepted-exception`. Don't assume the set of values stays closed. A missing key means the check wasn't recorded, or two working copies disagreed, and the reader must treat it as UNKNOWN.
  - A member with no working copy on the Mac has no row.
- **No secrets:** the feed holds no `details`, `fix`, `remediation`, or credential.
- **Freshness:** the scan writes the feed on every successful run, including runs with an unreadable member record, which exit 3. A run that raises leaves the previous feed in place, with its older `scanned_at`.
- **Formatting:** the bytes are `json.dumps(indent=2, sort_keys=True)` plus a newline. Parse the JSON, and don't rely on the formatting beyond determinism.
- **Mac carrier unchanged:** this step changes nothing in `portfolio.json`, so the orchestrator's `load_portfolio` keeps working until the cut-over.

## Standards followed

- **Code Brain rule 3 (structured JSON logs to stdout in production):** the diff adds no logging. The scan is a Mac CLI job, and its launcher keeps writing `~/.portfolio/scan.log` unchanged.
- **Code Brain rule 4 (never silently swallow an exception):** `write_feed` removes its temporary file and re-raises, and `scan()` doesn't catch the error, so the scan exits non-zero and the launcher pings `/fail`. Mutant M8 proves a test fails if the error is swallowed.
- **Code Brain rule 5 (never log secrets, credentials, or tokens):** the feed holds statuses only, never `details`, `fix`, or `remediation`, and no token. A test asserts that a marker planted in those fields is absent from the feed's bytes. The diff adds no logging.
- **Infra Brain 591, 592, and 593 (no BWS token in tracked files or history, and no inline `BWS_ACCESS_TOKEN` value):** the diff contains no token and no `BWS_ACCESS_TOKEN` assignment. The security scan reports 0 BLOCK findings.
- **Infra Brain 1032 (`cred.exposure-rotate`):** I saw no secret value during this work, so I have nothing to report.
- **Infra Brain 212 (HTTPS for public FQDNs):** doesn't apply. The diff makes no network change and adds no endpoint.
