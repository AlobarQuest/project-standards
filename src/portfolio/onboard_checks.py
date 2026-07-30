"""Per-repo onboarding checks (WS-P2.11).

Each check returns {id, status, details, fix, remediation}: `status` uses the
matrix vocabulary (pass/violation/unknown), `fix` names the exact next action,
and `remediation` (when not None) is the machine payload a failed ADMISSION
check contributes to the readiness result's remediation queue. Settings-only
fixes (Q5: the kit never writes GitHub settings) carry `fix` but no
`remediation`.

Remote reads go through the injectable `_gh` helper so tests construct failing
instances without the network; UNKNOWN is admission-failing by design — a
check that cannot see is never green.
"""

import base64
import json
import re
import sys
import tomllib
from pathlib import Path

from . import config
from .checkers import _run, check_security
from .contract import VERSIONED_STANDARDS, current_standard_versions
from .manifest import parse_frontmatter
from .matrix import PASS, UNKNOWN, VIOLATION
from .validator import lint


def _gh(args: list[str]) -> str | None:
    """Run `gh` and return stdout, or None on any failure."""
    result = _run(["gh", *args])
    if result is None or result.returncode != 0:
        return None
    return result.stdout


def _result(check_id, status, details=None, fix=None, remediation=None):
    return {
        "id": check_id,
        "status": status,
        "details": details or [],
        "fix": fix,
        "remediation": remediation,
    }


def _git(repo: Path, *args: str):
    return _run(["git", "-C", str(repo), *args])


def repo_slug(repo: Path) -> str | None:
    """`owner/name` from the origin remote, or None."""
    result = _git(repo, "remote", "get-url", "origin")
    if result is None or result.returncode != 0:
        return None
    url = result.stdout.strip()
    match = re.search(r"github\.com[:/]([^/]+/[^/\s]+?)(?:\.git)?$", url)
    return match.group(1) if match else None


def check_code_onboarded(repo: Path) -> dict:
    missing = []
    if not (repo / ".code-standards.toml").is_file():
        missing.append(
            {
                "id": "code.no-manifest",
                "message": ".code-standards.toml absent",
                "fix": f"cd {repo} && code-standards init",
            }
        )
    if not (repo / ".github/workflows/quality.yml").is_file():
        missing.append(
            {
                "id": "code.no-quality-workflow",
                "message": ".github/workflows/quality.yml absent",
                "fix": f"cd {repo} && code-standards sync",
            }
        )
    if missing:
        return _result(
            "code.onboarded",
            VIOLATION,
            details=[{"id": m["id"], "message": m["message"]} for m in missing],
            fix="; ".join(m["fix"] for m in missing),
            remediation={"summary": "onboard the repo to code-standards (init + sync)"},
        )
    return _result("code.onboarded", PASS)


_UUID_PROBE = (
    "import sys; from pathlib import Path; from security_scan import manifest; "
    "print(len(manifest.referenced_uuids(Path(sys.argv[1]))))"
)


def _referenced_uuid_count(repo: Path) -> int | None:
    result = _run(
        [sys.executable, "-c", _UUID_PROBE, str(repo)],
        env={"PYTHONPATH": str(config.security_standards_src())},
    )
    if result is None or result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


def _governance_registered(repo: Path) -> bool | None:
    map_path = config.security_standards_repo() / "governance-map.toml"
    try:
        parsed = tomllib.loads(map_path.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return None
    for entry in parsed.get("repo", []):
        if entry.get("name") == repo.name or Path(str(entry.get("path", ""))).name == repo.name:
            return True
    return False


def check_security_clean(repo: Path) -> dict:
    base = check_security(repo)
    if base.status != PASS:
        status = VIOLATION if base.status == VIOLATION else UNKNOWN
        return _result(
            "security.clean",
            status,
            details=base.details or [{"id": "security.unavailable", "message": base.note or ""}],
            fix=(
                f"PYTHONPATH={config.security_standards_src()} {sys.executable} -m "
                f"security_scan.cli {repo} --category security — remediate every BLOCK"
            ),
            remediation={"summary": "clear the security scanner's BLOCK findings"}
            if base.status == VIOLATION
            else None,
        )
    referenced = _referenced_uuid_count(repo)
    if referenced is None:
        return _result(
            "security.clean",
            UNKNOWN,
            details=[
                {"id": "security.bws-probe-failed", "message": "referenced_uuids probe failed"}
            ],
            fix="check SECURITY_STANDARDS_REPO points at a security-standards checkout",
        )
    if referenced == 0:
        return _result("security.clean", PASS)
    problems = []
    if not (repo / ".bws-secrets.toml").is_file():
        problems.append(
            {
                "id": "security.no-bws-manifest",
                "message": f"{referenced} BWS UUID reference(s) but no .bws-secrets.toml",
                "fix": (
                    f"PYTHONPATH={config.security_standards_src()} {sys.executable} -m "
                    f"security_scan.genmanifest {repo} --write"
                ),
            }
        )
    registered = _governance_registered(repo)
    if registered is None:
        return _result(
            "security.clean",
            UNKNOWN,
            details=[
                {"id": "security.map-unreadable", "message": "governance-map.toml unreadable"}
            ],
            fix="check the security-standards checkout",
        )
    if not registered:
        problems.append(
            {
                "id": "security.not-in-governance-map",
                "message": "BWS-consuming repo has no [[repo]] entry in governance-map.toml",
                "fix": (
                    "add a [[repo]] consumer entry for this repo to security-standards "
                    "governance-map.toml, then make ownership"
                ),
            }
        )
    if problems:
        return _result(
            "security.clean",
            VIOLATION,
            details=[{"id": p["id"], "message": p["message"]} for p in problems],
            fix="; ".join(p["fix"] for p in problems),
            remediation={"summary": "register the repo's BWS consumption (manifest + map entry)"},
        )
    return _result("security.clean", PASS)


def registered_profiles() -> list[str] | None:
    """Registered delivery-profile names, read from intent-packages by pointer."""
    result = _run(
        [
            "uv",
            "run",
            "--project",
            str(config.intent_packages_dir()),
            "python",
            "-c",
            "from intent_packages.profiles import PROFILES; print('\\n'.join(sorted(PROFILES)))",
        ]
    )
    if result is None or result.returncode != 0:
        return None
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return names or None


def check_profile_declared(repo: Path, registered_profiles: list[str] | None) -> dict:
    if registered_profiles is None:
        return _result(
            "profile.declared",
            UNKNOWN,
            details=[
                {"id": "profile.registry-unavailable", "message": "cannot read PROFILES registry"}
            ],
            fix="check INTENT_PACKAGES_DIR points at an intent-packages checkout",
        )
    manifest_path = repo / "PROJECT.md"
    declared = None
    if manifest_path.is_file():
        frontmatter, _ = parse_frontmatter(manifest_path.read_text())
        declared = frontmatter.get("delivery_profile")
    if declared not in registered_profiles:
        seen = "absent" if declared is None else f"{declared!r} (not registered)"
        return _result(
            "profile.declared",
            VIOLATION,
            details=[{"id": "profile.not-declared", "message": f"delivery_profile {seen}"}],
            fix=(
                "declare `delivery_profile: <name>` in PROJECT.md frontmatter; registered: "
                + ", ".join(registered_profiles)
            ),
            remediation={"summary": "declare the repo's delivery profile in PROJECT.md"},
        )
    return _result("profile.declared", PASS)


def check_dependabot(repo: Path) -> dict:
    if (repo / ".github" / "dependabot.yml").is_file():
        return _result("deps.dependabot", PASS)
    return _result(
        "deps.dependabot",
        VIOLATION,
        details=[{"id": "deps.no-dependabot", "message": ".github/dependabot.yml absent"}],
        fix=f"cd {repo} && code-standards sync (vendors a tooling-appropriate dependabot.yml)",
    )


def check_protection(slug: str, gh=_gh) -> dict:
    """Branch protection on main — CHECK-AND-REPORT only (Q5): the fix is a
    command Devon runs, never a queue item, and the kit never writes settings."""
    raw = gh(["api", f"repos/{slug}/branches/main/protection"])
    if raw is None:
        return _result(
            "repo.protection",
            VIOLATION,
            details=[{"id": "repo.unprotected", "message": "main has no branch protection"}],
            fix=(
                f"gh api -X PUT repos/{slug}/branches/main/protection "
                "-f required_pull_request_reviews.required_approving_review_count=1 "
                "(Devon runs this; the kit never writes settings)"
            ),
        )
    return _result("repo.protection", PASS)


def check_backlog_hygiene(repo: Path) -> dict:
    findings = lint(repo)
    aged = [f for f in findings if f.code == "aged_item"]
    if not aged:
        return _result("backlog.hygiene", PASS)
    return _result(
        "backlog.hygiene",
        VIOLATION,
        details=[{"id": "backlog.aged", "message": f.message} for f in aged],
        fix=f"triage or close the aged backlog items in {repo}/PROJECT.md",
    )


def check_standards_pinned(repo: Path) -> dict:
    manifest_path = repo / "PROJECT.md"
    if not manifest_path.is_file():
        return _result(
            "standards.pinned",
            UNKNOWN,
            details=[{"id": "standards.no-manifest", "message": "no PROJECT.md"}],
            fix="fix project.manifest first",
        )
    frontmatter, _ = parse_frontmatter(manifest_path.read_text())
    declared = frontmatter.get("applicable_standards") or {}
    current = current_standard_versions()
    drifted = []
    for std in VERSIONED_STANDARDS:
        pin = declared.get(std)
        current_version = current.get(std)
        if pin is None or current_version is None:
            continue
        if str(pin) != str(current_version):
            drifted.append(
                {
                    "id": f"standards.{std}-drift",
                    "message": f"{std}: pinned {pin}, current {current_version}",
                }
            )
    if drifted:
        return _result(
            "standards.pinned",
            VIOLATION,
            details=drifted,
            fix="update applicable_standards pins in PROJECT.md frontmatter",
        )
    return _result("standards.pinned", PASS)


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_USES_RE = re.compile(
    r"uses:\s*AlobarQuest/factory-runner/\.github/workflows/factory-runner\.yml@(\S+)"
)


def _gh_contents(slug_path: str, gh, ref: str | None = None) -> str | None:
    args = ["api", f"repos/{slug_path}" + (f"?ref={ref}" if ref else "")]
    raw = gh(args)
    if raw is None:
        return None
    try:
        content = json.loads(raw)["content"]
        return base64.b64decode(content).decode()
    except (ValueError, KeyError):
        return None


def declared_pin(gh=_gh) -> str | None:
    """The caller pin factory-runner declares in RECOMMENDED_CALLER_PIN."""
    text = _gh_contents(f"{config.factory_runner_slug()}/contents/RECOMMENDED_CALLER_PIN", gh)
    if text is None:
        return None
    pin = text.strip()
    return pin if _SHA_RE.match(pin) else None


def required_secrets(sha: str, gh=_gh) -> set[str] | None:
    """Secret names the reusable workflow requires, read AT the declared SHA —
    never hard-coded (the stale doc template passed 2 of 4)."""
    text = _gh_contents(
        f"{config.factory_runner_slug()}/contents/.github/workflows/factory-runner.yml",
        gh,
        ref=sha,
    )
    if text is None:
        return None
    match = re.search(r"workflow_call:.*?secrets:\n(.*?)\n\S", text, re.DOTALL)
    block = match.group(1) if match else ""
    names = {
        line.strip().rstrip(":")
        for line in block.splitlines()
        if line.strip().endswith(":") and line.strip().rstrip(":").isupper()
    }
    return names or None


def check_runner_caller(repo: Path, slug: str, gh=_gh) -> dict:
    caller = repo / ".github" / "workflows" / "factory-runner-pilot.yml"
    template = Path(__file__).parent / "templates" / "factory-runner-caller.yml"
    if not caller.is_file():
        return _result(
            "runner.caller",
            VIOLATION,
            details=[{"id": "runner.no-caller", "message": "factory-runner-pilot.yml absent"}],
            fix=(
                f"copy {template} to {caller}, filling the pin from factory-runner's "
                "RECOMMENDED_CALLER_PIN"
            ),
            remediation={"summary": "add the factory-runner caller workflow from the template"},
        )
    pin = declared_pin(gh=gh)
    if pin is None:
        return _result(
            "runner.caller",
            UNKNOWN,
            details=[
                {
                    "id": "runner.declared-pin-unreachable",
                    "message": "cannot read factory-runner RECOMMENDED_CALLER_PIN",
                }
            ],
            fix="check gh auth / that factory-runner declares RECOMMENDED_CALLER_PIN",
        )
    match = _USES_RE.search(caller.read_text())
    used = match.group(1) if match else None
    if used is None or not _SHA_RE.match(used):
        return _result(
            "runner.caller",
            VIOLATION,
            details=[
                {
                    "id": "runner.unpinned",
                    "message": f"caller uses @{used or '?'} — not a full SHA (GAP-4 class)",
                }
            ],
            fix=f"pin the caller's uses: to @{pin} (factory-runner's declared pin)",
            remediation={"summary": "SHA-pin the caller to the declared pin"},
        )
    if used != pin:
        return _result(
            "runner.caller",
            VIOLATION,
            details=[
                {
                    "id": "runner.behind-pin",
                    "message": f"caller pin {used[:12]} != declared pin {pin[:12]}",
                }
            ],
            fix=f"re-pin the caller's uses: to @{pin}",
            remediation={"summary": "re-pin the caller to factory-runner's declared pin"},
        )
    needed = required_secrets(pin, gh=gh)
    if needed is None:
        return _result(
            "runner.caller",
            UNKNOWN,
            details=[
                {
                    "id": "runner.secrets-unreadable",
                    "message": "cannot read the reusable workflow's secrets block",
                }
            ],
            fix="check gh auth and the declared pin, then re-run",
        )
    listing = gh(["secret", "list", "--repo", slug, "--json", "name"])
    if listing is None:
        return _result(
            "runner.caller",
            UNKNOWN,
            details=[{"id": "runner.secrets-list-failed", "message": "gh secret list failed"}],
            fix="check gh auth (secrets read needs admin), then re-run",
        )
    try:
        have = {entry["name"] for entry in json.loads(listing)}
    except (ValueError, TypeError, KeyError):
        have = set()
    missing = sorted(needed - have)
    if missing:
        return _result(
            "runner.caller",
            VIOLATION,
            details=[
                {
                    "id": "runner.missing-secrets",
                    "message": f"missing secrets: {', '.join(missing)}",
                }
            ],
            fix=f"gh secret set {' / '.join(missing)} --repo {slug} (values piped from BWS)",
        )
    return _result("runner.caller", PASS)


_COLLECTED_RE = re.compile(r"collected (\d+) items?")


def check_ci_executed(repo: Path, gh=_gh) -> dict:
    """Latest quality run on main must have succeeded AND provably executed
    tests — `collected N items`, N > 0, read from the job log. Never the check
    color alone: the vendored CI can pass having run nothing (every tool
    command -v guarded, pytest exit 5 swallowed, no-lockfile repos install
    nothing)."""
    slug = repo_slug(repo)
    if slug is None:
        return _result(
            "ci.executed",
            UNKNOWN,
            details=[{"id": "ci.no-origin", "message": "cannot derive GitHub slug from origin"}],
            fix=f"add a GitHub origin remote to {repo}",
        )
    listing = gh(
        [
            "run",
            "list",
            "--repo",
            slug,
            "--workflow",
            "quality.yml",
            "--branch",
            "main",
            "--limit",
            "1",
            "--json",
            "databaseId,conclusion",
        ]
    )
    if listing is None:
        return _result(
            "ci.executed",
            UNKNOWN,
            details=[{"id": "ci.gh-failed", "message": "gh run list failed"}],
            fix="check gh auth and network, then re-run",
        )
    try:
        runs = json.loads(listing)
    except ValueError:
        runs = None
    if not runs:
        return _result(
            "ci.executed",
            UNKNOWN,
            details=[{"id": "ci.no-runs", "message": "no quality.yml runs on main"}],
            fix=f"push to main (or re-run the workflow) in {slug}, then re-run this check",
        )
    run = runs[0]
    if run.get("conclusion") != "success":
        return _result(
            "ci.executed",
            VIOLATION,
            details=[
                {
                    "id": "ci.not-green",
                    "message": f"latest quality run concluded {run.get('conclusion')!r}",
                }
            ],
            fix=f"fix the failing quality run on {slug} main",
            remediation={"summary": "make the quality workflow green on main"},
        )
    log = gh(["run", "view", str(run.get("databaseId")), "--repo", slug, "--log"])
    if log is None:
        return _result(
            "ci.executed",
            UNKNOWN,
            details=[{"id": "ci.log-unreadable", "message": "gh run view --log failed"}],
            fix="check gh auth and network, then re-run",
        )
    match = _COLLECTED_RE.search(log)
    if match is None or int(match.group(1)) == 0:
        found = "no 'collected N items' line" if match is None else "collected 0 items"
        return _result(
            "ci.executed",
            VIOLATION,
            details=[{"id": "ci.ran-nothing", "message": f"run succeeded but {found}"}],
            fix=(
                f"the green check on {slug} proves nothing ran: ensure pytest is installed by "
                "CI (dependency-groups, not optional-dependencies) and tests are collected — "
                "then verify the log shows 'collected N items' with N > 0"
            ),
            remediation={"summary": "make CI actually execute the test suite"},
        )
    return _result(
        "ci.executed",
        PASS,
        details=[{"id": "ci.collected", "message": f"collected {match.group(1)} items"}],
    )


def check_git_current(repo: Path) -> dict:
    fetch = _git(repo, "fetch", "--quiet", "origin", "main")
    if fetch is None or fetch.returncode != 0:
        message = "" if fetch is None else (fetch.stderr or fetch.stdout).strip()
        return _result(
            "git.current",
            VIOLATION,
            details=[{"id": "git.fetch-failed", "message": f"git fetch origin main: {message}"}],
            fix=f"ensure {repo} has an 'origin' remote on GitHub and network access, then re-run",
        )
    head = _git(repo, "rev-parse", "HEAD")
    remote = _git(repo, "rev-parse", "origin/main")
    if head is None or remote is None or head.returncode != 0 or remote.returncode != 0:
        return _result(
            "git.current",
            UNKNOWN,
            details=[
                {"id": "git.rev-parse-failed", "message": "could not resolve HEAD/origin/main"}
            ],
            fix=f"inspect {repo} by hand; rev-parse failed",
        )
    if head.stdout.strip() != remote.stdout.strip():
        return _result(
            "git.current",
            VIOLATION,
            details=[
                {
                    "id": "git.not-origin-main",
                    "message": (
                        f"HEAD {head.stdout.strip()[:12]} != origin/main "
                        f"{remote.stdout.strip()[:12]}"
                    ),
                }
            ],
            fix=f"git -C {repo} checkout main && git -C {repo} pull --ff-only origin main",
            remediation={"summary": "bring the checkout to current origin/main"},
        )
    status = _git(repo, "status", "--porcelain")
    if status is None or status.returncode != 0:
        return _result(
            "git.current",
            UNKNOWN,
            details=[{"id": "git.status-failed", "message": "git status failed"}],
            fix=f"inspect {repo} by hand",
        )
    if status.stdout.strip():
        return _result(
            "git.current",
            VIOLATION,
            details=[{"id": "git.dirty", "message": "worktree has uncommitted changes"}],
            fix=f"commit, stash, or discard the changes in {repo}, then re-run",
        )
    return _result("git.current", PASS)
