# Final-Review Fix Report

**Branch:** build/portfolio-toolkit  
**Date:** 2026-06-25

## Fixes Applied

1. **Fix 1 (query first-run guard):** `src/portfolio/query.py` — restructured top of `query()` to return `[]` when `json_text is None` and `config.json_path()` does not exist, preventing FileNotFoundError on first run. Test `test_query_missing_json_returns_empty` added.

2. **Fix 2 (drop dead find_duplicate):** `src/portfolio/inbox.py` — removed `find_duplicate` function entirely. `tests/test_inbox.py` — removed `test_find_duplicate` test and `find_duplicate` from the import line.

3. **Fix 3 (init version_source no-clobber):** `src/portfolio/init.py` — when version is blank, fills `version` from detection but uses `setdefault` for `version_source` so a human-set value is preserved. Test `test_init_preserves_human_version_source_when_version_blank` added.

4. **Fix 4 (malformed-yaml assertion hardened):** `tests/test_robustness.py` — changed `summary["projects"] >= 1` to `summary["projects"] == 2` confirming both repos (`bad` and `bad2`) were discovered.

5. **Fix 5 (no cwd leak):** `tests/test_cli.py` — replaced `import os; os.chdir(repo)` with `monkeypatch.chdir(repo)` and added `monkeypatch` to the test's parameter list.

6. **Fix 6 (coverage):** Added `test_query_filters_by_has_backlog` and `test_query_filters_by_tag` to `tests/test_query.py`; added `test_scan_counts_fails` to `tests/test_scan.py`; added `test_init_preserves_human_version_source_when_version_blank` to `tests/test_init.py`.

## Full Suite Result

```
61 passed
```

All 61 tests green (net: -1 deleted find_duplicate test, +6 new = 6 additions, 1 deletion from prior baseline of ~56).
