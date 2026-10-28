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
                subprocess.run(
                    [
                        "git",
                        "-c",
                        "user.email=t@t",
                        "-c",
                        "user.name=t",
                        "commit",
                        "-q",
                        "--allow-empty",
                        "-m",
                        "init",
                    ],
                    cwd=repo,
                    check=True,
                )
        return repo

    return _make


@pytest.fixture
def standards_env(monkeypatch, tmp_path):
    """Fake standards repos with STANDARD_VERSION files, so tests never read
    the real ~/Projects checkouts. Returns the dict of repo paths."""
    repos = {}
    for std, env in (
        ("project", "PROJECT_STANDARDS_REPO"),
        ("code", "CODE_STANDARDS_REPO"),
        ("security", "SECURITY_STANDARDS_REPO"),
    ):
        repo = tmp_path / f".std-{std}"
        repo.mkdir()
        (repo / "STANDARD_VERSION").write_text("1.0\n")
        monkeypatch.setenv(env, str(repo))
        repos[std] = repo
    return repos


@pytest.fixture(autouse=True)
def _no_dispatch_app_key(monkeypatch):
    """No test may read the real Dispatch App private key from the operator's shell.

    `factory.app_access` reads its credential from the environment, so a
    developer who has exported the live key would have the suite sign a JWT,
    call GitHub, and — under a repository-selected installation — MINT A TOKEN.
    A suite whose behaviour depends on whether a production private key happens
    to be exported is not a suite. Scrubbed globally rather than per-test so a
    future test cannot forget; every test that needs a reach injects one.

    The name comes from `config`, never spelled again here: a literal would be a
    second copy, and renaming the variable would leave this guard silently
    guarding nothing — in the fixture whose whole job is hermeticity.
    """
    from portfolio import config

    monkeypatch.delenv(config.DISPATCH_APP_KEY_ENV, raising=False)


@pytest.fixture(autouse=True)
def _no_sds_observer_token(monkeypatch):
    """No test may read the live SDS member record with the operator's bearer.

    `scan` reads the member record when nothing is injected, so an exported
    observer token would put the orchestrator on the path of every scan test.
    Scrubbed globally for the same reason as the App key; a test that needs a
    scope injects `read_scope`.
    """
    from portfolio import config

    monkeypatch.delenv(config.SDS_OBSERVER_TOKEN_ENV, raising=False)
