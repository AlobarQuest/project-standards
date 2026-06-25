import os
from pathlib import Path

DEFAULT_ROOTS = [Path.home() / "Projects", Path.home() / "Developer"]
STALE_DAYS = 30
BACKLOG_AGE_DAYS = 180

def portfolio_home() -> Path:
    override = os.environ.get("PORTFOLIO_HOME")
    return Path(override) if override else Path.home() / ".portfolio"

def inbox_path() -> Path:  return portfolio_home() / "inbox.jsonl"
def json_path() -> Path:   return portfolio_home() / "portfolio.json"
def digest_path() -> Path: return portfolio_home() / "PORTFOLIO.md"
