from datetime import date, datetime
from pathlib import Path

from . import config
from .schema import Finding, validate_frontmatter
from .manifest import read_manifest, parse_backlog
from .detect import is_git

def lint(repo: Path, today: date | None = None) -> list[Finding]:
    today = today or date.today()
    m = read_manifest(repo)
    if m is None:
        return [Finding("FAIL", "missing_manifest", f"{repo.name}: no PROJECT.md")]
    if "_yaml_error" in m.frontmatter:                      # [debate-fix]
        return [Finding("FAIL", "bad_yaml", f"{repo.name}: invalid frontmatter: {m.frontmatter['_yaml_error']}")]
    findings = list(validate_frontmatter(m.frontmatter))
    tier = m.frontmatter.get("tier")
    if not is_git(repo):
        findings.append(Finding("FAIL" if tier == "active" else "WARN", "not_git", f"{repo.name}: not a git repo"))
    for item in parse_backlog(m.body):
        if item.malformed:
            findings.append(Finding("WARN", "malformed_item", f"{repo.name}: malformed backlog line: {item.raw.strip()}"))
        elif item.added:
            try:
                if (today - datetime.strptime(item.added, "%Y-%m-%d").date()).days > config.BACKLOG_AGE_DAYS:
                    findings.append(Finding("WARN", "aged_item", f"{repo.name}: aged backlog item: {item.text}"))
            except ValueError:
                findings.append(Finding("WARN", "malformed_item", f"{repo.name}: bad date: {item.raw.strip()}"))
    return findings
