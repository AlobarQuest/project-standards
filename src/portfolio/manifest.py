import re
from dataclasses import dataclass
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
# [debate-fix] tolerate em/en/ascii/double dash as the "added" separator
BACKLOG_LINE_RE = re.compile(
    r"^- \[[ xX]\] (?:\((?P<priority>P\d)\) )?(?P<text>.*?)"
    r"(?:\s+[—–-]{1,2}\s+added\s+(?P<added>\d{4}-\d{2}-\d{2}))?\s*$"
)


@dataclass
class Manifest:
    frontmatter: dict
    body: str
    path: Path


@dataclass
class BacklogItem:
    text: str
    priority: str | None
    added: str | None
    raw: str
    malformed: bool


def parse_frontmatter(text: str) -> tuple[dict, str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    try:  # [debate-fix]
        fm = yaml.safe_load(match.group(1)) or {}
        if not isinstance(fm, dict):
            return {"_yaml_error": "frontmatter is not a mapping"}, match.group(2)
    except yaml.YAMLError as e:
        return {"_yaml_error": str(e)}, match.group(2)
    return fm, match.group(2)


def render(fm: dict, body: str) -> str:
    front = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False).rstrip("\n")
    return f"---\n{front}\n---\n\n{body.lstrip(chr(10))}"


def read_manifest(repo: Path) -> Manifest | None:
    path = repo / "PROJECT.md"
    if not path.exists():
        return None
    fm, body = parse_frontmatter(path.read_text())
    return Manifest(frontmatter=fm, body=body, path=path)


def write_manifest(m: Manifest) -> None:
    m.path.write_text(render(m.frontmatter, m.body))


def factory_target_declaration(repo: Path) -> tuple[bool | None, str | None]:
    """A repo's own answer to "do I want to be a factory target?" (ADR-0015).

    Returns (declared, reason): `declared` is the frontmatter `factory_target`
    when it is a real bool and None otherwise -- an absent key, a string
    `"false"`, a missing manifest and unreadable YAML all read as "nothing
    declared", never as "declared false". That direction is deliberate: a
    declaration is what turns a check's `violation` into `not-applicable`, so
    anything short of an unambiguous bool must leave the check where it was.
    The schema validator FAILs a non-bool value, so a typo is loud rather than
    silently inert.
    """
    m = read_manifest(repo)
    if m is None or "_yaml_error" in m.frontmatter:
        return None, None
    declared = m.frontmatter.get("factory_target")
    if not isinstance(declared, bool):
        return None, None
    reason = m.frontmatter.get("factory_target_reason")
    return declared, reason if isinstance(reason, str) and reason.strip() else None


def parse_backlog(body: str) -> list[BacklogItem]:
    items, in_section = [], False
    for line in body.splitlines():
        if line.strip().lower() == "## backlog":
            in_section = True
            continue
        if line.startswith("## ") and in_section:
            break
        if in_section and line.strip().startswith("- ["):
            m = BACKLOG_LINE_RE.match(line.rstrip())
            if m:
                items.append(
                    BacklogItem(
                        m.group("text").strip(),
                        m.group("priority"),
                        m.group("added"),
                        line,
                        malformed=False,
                    )
                )
            else:
                items.append(BacklogItem(line.strip(), None, None, line, malformed=True))
    return items


def append_backlog_item(repo: Path, text: str, priority: str | None, added: str) -> None:
    path = repo / "PROJECT.md"
    content = path.read_text()
    prefix = f"({priority}) " if priority else ""
    new_line = f"- [ ] {prefix}{text} — added {added}"  # canonical em-dash
    lines, out, inserted = content.splitlines(), [], False
    for i, line in enumerate(lines):
        out.append(line)
        if not inserted and line.strip().lower() == "## backlog":
            j = i + 1
            while j < len(lines) and (lines[j].strip().startswith("- [") or not lines[j].strip()):
                out.append(lines[j])
                j += 1
            out.append(new_line)
            inserted = True
            out.extend(lines[j:])
            break
    if not inserted:
        out += ["", "## Backlog", new_line]
    path.write_text("\n".join(out) + ("\n" if content.endswith("\n") else ""))
