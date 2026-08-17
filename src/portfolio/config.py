import os
from pathlib import Path

DEFAULT_ROOTS = [Path.home() / "Projects", Path.home() / "Developer"]
STALE_DAYS = 30
BACKLOG_AGE_DAYS = 180
FOUNDATION_TIMEOUT_S = 120
INFRA_MAX_AGE_H = 36


def portfolio_home() -> Path:
    override = os.environ.get("PORTFOLIO_HOME")
    return Path(override) if override else Path.home() / ".portfolio"


def inbox_path() -> Path:
    return portfolio_home() / "inbox.jsonl"


def json_path() -> Path:
    return portfolio_home() / "portfolio.json"


def digest_path() -> Path:
    return portfolio_home() / "PORTFOLIO.md"


def security_standards_repo() -> Path:
    override = os.environ.get("SECURITY_STANDARDS_REPO")
    return Path(override) if override else Path.home() / "Projects" / "security-standards"


def security_standards_src() -> Path:
    return security_standards_repo() / "src"


def code_standards_repo() -> Path:
    override = os.environ.get("CODE_STANDARDS_REPO")
    return Path(override) if override else Path.home() / "Developer" / "code-standards"


def infra_report_dir() -> Path:
    override = os.environ.get("INFRADRIFT_REPORT_DIR")
    return Path(override) if override else Path.home() / "infra-drift" / "reports"


def exceptions_path() -> Path:
    override = os.environ.get("FOUNDATION_EXCEPTIONS")
    return (
        Path(override)
        if override
        else Path(__file__).resolve().parents[2] / "foundation-exceptions.toml"
    )


def foundation_json_path() -> Path:
    return portfolio_home() / "foundation.json"


def foundation_digest_path() -> Path:
    return portfolio_home() / "FOUNDATION.md"


def checker_timeout() -> int:
    override = os.environ.get("FOUNDATION_TIMEOUT")
    try:
        return int(override) if override else FOUNDATION_TIMEOUT_S
    except ValueError:
        return FOUNDATION_TIMEOUT_S


def infra_max_age_hours() -> int:
    override = os.environ.get("INFRA_MAX_AGE_HOURS")
    try:
        return int(override) if override else INFRA_MAX_AGE_H
    except ValueError:
        return INFRA_MAX_AGE_H


def project_standards_repo() -> Path:
    override = os.environ.get("PROJECT_STANDARDS_REPO")
    return Path(override) if override else Path(__file__).resolve().parents[2]


def standards_repos() -> dict[str, Path]:
    return {
        "project": project_standards_repo(),
        "code": code_standards_repo(),
        "security": security_standards_repo(),
    }


def claude_settings_path() -> Path:
    override = os.environ.get("CLAUDE_SETTINGS_JSON")
    return Path(override) if override else Path.home() / ".claude" / "settings.json"


def launchagents_dir() -> Path:
    override = os.environ.get("LAUNCHAGENTS_DIR")
    return Path(override) if override else Path.home() / "Library" / "LaunchAgents"


def intent_packages_dir() -> Path:
    override = os.environ.get("INTENT_PACKAGES_DIR")
    return Path(override) if override else Path.home() / "Projects" / "intent-packages"


def factory_runner_slug() -> str:
    return os.environ.get("FACTORY_RUNNER_SLUG", "AlobarQuest/factory-runner")


# Q2 (factory capability) credentials. The kit READS these from the environment and
# never fetches them: a conformance tool that reaches for secrets is a different
# security surface from one that reads files, and this one is meant to run in more
# places than the operator's machine. Absent => the check reports `unknown` with a
# named reason, never `pass` and never `violation`. The launcher
# (integrations/portfolio-scan.sh) is where BWS is consulted.
FACTORY_PAT_ENV = "FACTORY_PR_TOKEN"
APP_BRAIN_KEY_ENV = "APP_BRAIN_READ_KEY"


def factory_pat() -> str | None:
    return os.environ.get(FACTORY_PAT_ENV) or None


def app_brain_url() -> str:
    return os.environ.get("APP_BRAIN_URL") or "https://app-brain.devonwatkins.com"


def app_brain_read_key() -> str | None:
    return os.environ.get(APP_BRAIN_KEY_ENV) or None
