import json
import subprocess
import tomllib
from pathlib import Path

def detect_name(repo: Path) -> str:
    return repo.name

def is_git(repo: Path) -> bool:
    return (repo / ".git").exists()   # True for both .git dir and worktree .git file

def detect_version(repo: Path) -> tuple[str, str]:
    pkg = repo / "package.json"
    if pkg.exists():
        try:
            v = json.loads(pkg.read_text()).get("version")
            if v: return str(v), "package.json"
        except (json.JSONDecodeError, OSError): pass
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
            v = data.get("project", {}).get("version") or data.get("tool", {}).get("poetry", {}).get("version")
            if v: return str(v), "pyproject"
        except (tomllib.TOMLDecodeError, OSError): pass
    cargo = repo / "Cargo.toml"
    if cargo.exists():
        try:
            v = tomllib.loads(cargo.read_text()).get("package", {}).get("version")
            if v: return str(v), "cargo"
        except (tomllib.TOMLDecodeError, OSError): pass
    if is_git(repo):
        tag = _git(repo, ["describe", "--tags", "--abbrev=0"])
        if tag: return tag, "git-tag"
    return "n/a", "none"

def detect_remote(repo: Path) -> str | None:
    return _git(repo, ["remote", "get-url", "origin"]) or None if is_git(repo) else None

def detect_purpose(repo: Path) -> str | None:
    readme = repo / "README.md"
    if not readme.exists(): return None
    for line in readme.read_text().splitlines():
        s = line.strip()
        if s and not s.startswith(("#", "!", "[")):
            return s
    return None

def _git(repo: Path, args: list[str]) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else None
    except (subprocess.SubprocessError, OSError):
        return None
