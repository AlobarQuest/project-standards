"""integrations/portfolio-scan.sh: the BWS fetch of FACTORY_PR_TOKEN and its Healthchecks pings.

The launcher runs for real under bash, with `security`, `bws` and `curl` replaced by fakes on
PATH and the scan's interpreter replaced through PORTFOLIO_PYTHON. The fake interpreter records
the FACTORY_PR_TOKEN the scan was handed, which is how these tests see which token reached it
without the launcher ever printing one.
"""

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[1] / "integrations" / "portfolio-scan.sh"

PAT_UUID = "a3240c2e-92d7-4b32-a726-b49b0135565a"
HC_KEY_UUID = "260cc8ad-f170-44cc-a672-b47000df3350"
BROAD = "fake-broad-identity-5e1f"
NARROW = "fake-narrow-identity-8c2a"
PAT = "fake-pat-from-bws-7f3a"
STALE_PAT = "fake-stale-pat-from-file-9b1c"
HC_KEY = "fake-hc-api-key-2d4e"
PING_URL = "https://hc-ping.test/fake-ping-secret-41d0"
WRONG = "https://hc-ping.test/near-miss"
SECRETS = (BROAD, NARROW, PAT, STALE_PAT, HC_KEY, PING_URL)

FAKE_SECURITY = f"""#!/bin/bash
account=""
while [ $# -gt 0 ]; do [ "$1" = "-a" ] && account="$2"; shift; done
case "$account" in
  BWS_ACCESS_TOKEN_VPS_BACKUP) echo "{BROAD}" ;;
  BWS_ACCESS_TOKEN_SDS) [ -n "${{FAKE_NO_NARROW:-}}" ] && exit 44; echo "{NARROW}" ;;
  *) exit 44 ;;
esac
"""

# Refuses exactly what the launcher must never do: leak a colour-forcing variable, omit
# `--color no`, or present the wrong identity for a secret.
FAKE_BWS = f"""#!/bin/bash
[ -z "${{FORCE_COLOR+x}}${{CLICOLOR_FORCE+x}}" ] || {{ echo "colour forced" >&2; exit 9; }}
case " $* " in *" --color no "*) ;; *) echo "no --color no" >&2; exit 9 ;; esac
case "$3" in
  {HC_KEY_UUID}) [ "$BWS_ACCESS_TOKEN" = "{BROAD}" ] || exit 7; value="{HC_KEY}" ;;
  {PAT_UUID})
    [ "$BWS_ACCESS_TOKEN" = "{NARROW}" ] || exit 7
    [ -z "${{FAKE_BWS_PAT_FAILS:-}}" ] || {{ echo "[400 Bad Request]" >&2; exit 1; }}
    value="${{FAKE_BWS_PAT_VALUE-{PAT}}}" ;;
  *) exit 7 ;;
esac
printf '{{"id": "%s", "value": "%s"}}\\n' "$3" "$value"
"""

FAKE_CURL = f"""#!/bin/bash
for arg in "$@"; do
  case "$arg" in
    https://*) url="$arg" ;;
  esac
done
printf '%s\\n' "$url" >> "$FAKE_CURL_LOG"
if [ "$url" = "https://healthchecks.io/api/v3/checks/" ]; then
  case " $* " in *"X-Api-Key: {HC_KEY}"*) ;; *) exit 22 ;; esac
  printf '%s' "$FAKE_LISTING"
fi
"""

FAKE_PYTHON = """#!/bin/bash
if [ "$1" = "-c" ]; then exit 0; fi
printf '%s' "${FACTORY_PR_TOKEN-<unset>}" > "$FAKE_SEEN"
echo '{"projects": 0, "fails": 0, "warns": 0}'
exit "${FAKE_SCAN_RC:-0}"
"""


def _listing(*names):
    # Only the exact name carries the real ping url, so pinging a near-miss shows up as a ping.
    return json.dumps(
        {
            "checks": [
                {"name": n, "ping_url": PING_URL if n == "portfolio-scan" else f"{WRONG}/{n}"}
                for n in names
            ]
        }
    )


def _executable(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def run(tmp_path):
    home = tmp_path / "home"
    (home / ".portfolio").mkdir(parents=True)
    (home / ".portfolio" / "credentials.env").write_text(
        f"FACTORY_PR_TOKEN={STALE_PAT}\nAPP_BRAIN_READ_KEY=fake-brain\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "security", FAKE_SECURITY)
    _executable(bin_dir / "bws", FAKE_BWS)
    _executable(bin_dir / "curl", FAKE_CURL)
    python = tmp_path / "fake-python"
    _executable(python, FAKE_PYTHON)
    curl_log = tmp_path / "curl.log"
    seen = tmp_path / "seen"

    def _run(**extra):
        env = {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HOME": str(home),
            "PORTFOLIO_PYTHON": str(python),
            "FAKE_CURL_LOG": str(curl_log),
            "FAKE_SEEN": str(seen),
            "FAKE_LISTING": _listing("portfolio-scan-old", "portfolio-scan"),
            # Set on every run: the launcher must strip both before calling `bws`.
            "FORCE_COLOR": "1",
            "CLICOLOR_FORCE": "1",
            # A stale export in the calling shell must not stand in for BWS either.
            "FACTORY_PR_TOKEN": STALE_PAT,
            **extra,
        }
        proc = subprocess.run(
            ["bash", str(LAUNCHER)], env=env, capture_output=True, text=True, timeout=60
        )
        log = (home / ".portfolio" / "scan.log").read_text()
        for secret in SECRETS:
            assert secret not in proc.stdout + proc.stderr + log, "a secret value was printed"
        urls = curl_log.read_text().split() if curl_log.exists() else []
        assert not [u for u in urls if u.startswith(WRONG)], "a near-miss check was pinged"
        pings = [u.removeprefix(PING_URL) or "/" for u in urls if u.startswith(PING_URL)]
        return proc, pings, (seen.read_text() if seen.exists() else None), log

    return _run


def test_fetched_token_reaches_the_scan_and_pings_success(run):
    proc, pings, seen, log = run()
    assert proc.returncode == 0, proc.stderr
    assert pings == ["/start", "/"]
    assert seen == PAT
    assert "pat=bws" in log


def test_fetch_failure_pings_fail_and_still_runs_the_scan_without_the_token(run):
    proc, pings, seen, log = run(FAKE_BWS_PAT_FAILS="1")
    assert proc.returncode == 3
    assert pings == ["/start", "/fail"]
    assert seen == ""  # the scan ran, with neither the stale file value nor the stale export
    assert "pat=no(bws fetch failed or returned empty)" in log
    assert "FACTORY_PR_TOKEN was not read from BWS" in proc.stderr


def test_empty_value_is_a_fetch_failure(run):
    proc, pings, seen, _ = run(FAKE_BWS_PAT_VALUE="")
    assert proc.returncode == 3
    assert pings == ["/start", "/fail"]
    assert seen == ""


def test_missing_narrow_identity_is_a_fetch_failure(run):
    proc, pings, seen, log = run(FAKE_NO_NARROW="1")
    assert proc.returncode == 3
    assert pings == ["/start", "/fail"]
    assert seen == ""
    assert "pat=no(no narrow BWS identity)" in log


def test_scan_failure_passes_its_code_through_and_pings_fail(run):
    proc, pings, seen, log = run(FAKE_SCAN_RC="1")
    assert proc.returncode == 1
    assert pings == ["/start", "/fail"]
    assert seen == PAT
    assert "FAIL(rc=1)" in log


def test_only_an_exact_check_name_is_pinged(run):
    proc, pings, seen, _ = run(FAKE_LISTING=_listing("portfolio-scan-old", "portfolio-scans"))
    assert proc.returncode == 0
    assert pings == []
    assert seen == PAT
    assert "no check named 'portfolio-scan'" in proc.stderr
