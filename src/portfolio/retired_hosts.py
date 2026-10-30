import subprocess
import tomllib
from pathlib import Path

from . import config
from .schema import Finding

# Records of what was true at the time. They keep their addresses on purpose.
HISTORICAL_PATHS = ("docs/superpowers", "docs/decisions", "docs/reports", "tests")
# A dated report outside those paths opts out by carrying this text.
HISTORICAL_MARKER = "retired-hosts: historical"
REQUIRED_FIELDS = ("address", "label", "replacement")


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "rb") as f:
        hosts = tomllib.load(f).get("host", [])
    for host in hosts:
        if not all(isinstance(host.get(field), str) and host[field] for field in REQUIRED_FIELDS):
            raise ValueError(f"{path}: host entry needs {REQUIRED_FIELDS}: {host}")
    return hosts


def _git_grep(repo: Path, needle: str, pathspecs: tuple[str, ...] = ()) -> set[str]:
    """Tracked files containing `needle`. Raises if git can't answer."""
    cmd = ["git", "-C", str(repo), "grep", "-lIF", "-e", needle, "--", *pathspecs]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=config.FOUNDATION_TIMEOUT_S, check=False
    )
    if result.returncode > 1:
        raise OSError(result.stderr.strip())
    return set(result.stdout.splitlines())


def scan(repo: Path) -> list[Finding]:
    """One WARN per file and retired host, or a WARN saying the scan didn't run."""
    excludes = tuple(f":(exclude){path}" for path in HISTORICAL_PATHS)
    try:
        hosts = load(config.retired_hosts_path())
        if not hosts:
            return []
        historical = _git_grep(repo, HISTORICAL_MARKER)
        return [
            Finding(
                "WARN",
                "retired_host",
                f"{repo.name}: {name} names {host['label']} {host['address']}, "
                f"retired {host.get('retired', '')}: use {host['replacement']}",
            )
            for host in hosts
            for name in sorted(_git_grep(repo, host["address"], excludes) - historical)
        ]
    except (OSError, ValueError, tomllib.TOMLDecodeError, subprocess.TimeoutExpired) as error:
        return [Finding("WARN", "retired_host_unmeasured", f"{repo.name}: {error}")]
