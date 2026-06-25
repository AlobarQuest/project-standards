import subprocess
import pytest

@pytest.fixture
def portfolio_env(monkeypatch, tmp_path):
    # leading dot so the scanner (which skips dotted dirs) never counts the
    # portfolio home as a project when tmp_path doubles as a scan root.
    home = tmp_path / ".portfolio_home"
    home.mkdir()
    monkeypatch.setenv("PORTFOLIO_HOME", str(home))
    return home

@pytest.fixture
def make_repo(tmp_path):
    def _make(name, git=True, files=None, commit=True):
        repo = tmp_path / name
        repo.mkdir()
        for rel, content in (files or {}).items():
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        if git:
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            if commit:
                subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
                subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                                "commit", "-q", "--allow-empty", "-m", "init"], cwd=repo, check=True)
        return repo
    return _make
