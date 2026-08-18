# shellcheck shell=bash
# Resolve an interpreter that can actually run this package, and fail loudly if none.
#
# WHY THIS EXISTS. The launchers call `python3`, and under launchd that is not the
# `python3` an interactive shell resolves: the 2026-08-17 03:00 scan ran Xcode's
# Python 3.9 and died at import on `str | None`, which is PEP 604 syntax this package
# uses widely without `from __future__ import annotations`. The job had been failing
# that way unnoticed -- three successful runs in the whole log -- while the estate
# relied on its output to report standards drift.
#
# Version-probing rather than a hardcoded path: a homebrew prefix is one machine's
# answer, and `requires-python` is the package's own. Failing loudly rather than
# falling back: a scan that runs under the wrong interpreter is a scan that reports
# nothing while looking scheduled, which is the failure mode this whole file is about.
portfolio_python() {
  local min_major=3 min_minor=12 candidate
  for candidate in \
    "${PORTFOLIO_PYTHON:-}" \
    "$(command -v python3.13 2>/dev/null || true)" \
    "$(command -v python3.12 2>/dev/null || true)" \
    /opt/homebrew/bin/python3 \
    /usr/local/bin/python3 \
    "$(command -v python3 2>/dev/null || true)"
  do
    if [ -z "$candidate" ] || [ ! -x "$candidate" ]; then
      continue
    fi
    if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= ($min_major, $min_minor) else 1)" 2>/dev/null; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  echo "portfolio: no python3 >= ${min_major}.${min_minor} found (this package's requires-python)." >&2
  echo "  Set PORTFOLIO_PYTHON to an interpreter that satisfies it." >&2
  return 1
}
