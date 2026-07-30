import subprocess

import pytest

from portfolio import onboard_checks
from portfolio.matrix import PASS, VIOLATION, CheckResult
from portfolio.onboard_checks import check_profile_declared, check_security_clean


@pytest.fixture
def security_env(monkeypatch, tmp_path):
    std = tmp_path / "security-standards"
    std.mkdir()
    monkeypatch.setenv("SECURITY_STANDARDS_REPO", str(std))
    return std


def _base(status, details=None):
    return CheckResult("security", status, details=details or [])


def _uuid_probe(count):
    """Fake the referenced-uuids subprocess probe."""

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        if "-c" in cmd:
            return subprocess.CompletedProcess(args=[], returncode=0, stdout=f"{count}\n")
        raise AssertionError(f"unexpected _run: {cmd}")

    return fake_run


def test_security_block_fires(monkeypatch, make_repo, security_env):
    repo = make_repo("x")
    monkeypatch.setattr(onboard_checks, "check_security", lambda r: _base(VIOLATION))
    result = check_security_clean(repo)
    assert result["status"] == "violation"
    assert "security_scan" in result["fix"]


def test_security_unknown_never_green(monkeypatch, make_repo, security_env):
    repo = make_repo("x")
    monkeypatch.setattr(onboard_checks, "check_security", lambda r: _base("unknown"))
    assert check_security_clean(repo)["status"] == "unknown"


def test_non_bws_repo_passes_without_manifest(monkeypatch, make_repo, security_env):
    repo = make_repo("x")
    monkeypatch.setattr(onboard_checks, "check_security", lambda r: _base(PASS))
    monkeypatch.setattr(onboard_checks, "_run", _uuid_probe(0))
    assert check_security_clean(repo)["status"] == "pass"


def test_bws_repo_missing_manifest_fires(monkeypatch, make_repo, security_env):
    repo = make_repo("x")
    monkeypatch.setattr(onboard_checks, "check_security", lambda r: _base(PASS))
    monkeypatch.setattr(onboard_checks, "_run", _uuid_probe(3))
    (security_env / "governance-map.toml").write_text(
        f'[[repo]]\nname = "x"\npath = "{repo}"\nclass = "consumer"\nlane = "l"\n'
        'owns = []\nconsumers = []\nuses_bws = true\nremote = "r"\n'
    )
    result = check_security_clean(repo)
    assert result["status"] == "violation"
    assert "genmanifest" in result["fix"]


def test_bws_repo_missing_governance_entry_fires(monkeypatch, make_repo, security_env):
    repo = make_repo("x", files={".bws-secrets.toml": "# manifest\n"})
    monkeypatch.setattr(onboard_checks, "check_security", lambda r: _base(PASS))
    monkeypatch.setattr(onboard_checks, "_run", _uuid_probe(3))
    (security_env / "governance-map.toml").write_text('[[repo]]\nname = "other"\n')
    result = check_security_clean(repo)
    assert result["status"] == "violation"
    assert "governance-map.toml" in result["fix"]


def test_bws_repo_fully_registered_passes(monkeypatch, make_repo, security_env):
    repo = make_repo("x", files={".bws-secrets.toml": "# manifest\n"})
    monkeypatch.setattr(onboard_checks, "check_security", lambda r: _base(PASS))
    monkeypatch.setattr(onboard_checks, "_run", _uuid_probe(3))
    (security_env / "governance-map.toml").write_text(f'[[repo]]\nname = "x"\npath = "{repo}"\n')
    assert check_security_clean(repo)["status"] == "pass"


def test_uuid_probe_failure_is_unknown(monkeypatch, make_repo, security_env):
    repo = make_repo("x")
    monkeypatch.setattr(onboard_checks, "check_security", lambda r: _base(PASS))
    monkeypatch.setattr(onboard_checks, "_run", lambda *a, **k: None)
    assert check_security_clean(repo)["status"] == "unknown"


# --- profile.declared -----------------------------------------------------

REGISTERED = ["dependency-update", "maintenance-remediation", "software-delivery"]


def _manifest(extra=""):
    return f"---\nname: x\ntier: active\nstatus: active\n{extra}---\n\n## Backlog\n"


def test_profile_missing_fires_naming_registered(make_repo):
    repo = make_repo("x", files={"PROJECT.md": _manifest()})
    result = check_profile_declared(repo, registered_profiles=REGISTERED)
    assert result["status"] == "violation"
    assert "delivery_profile" in result["fix"]
    assert "software-delivery" in result["fix"]


def test_profile_unknown_name_fires(make_repo):
    repo = make_repo("x", files={"PROJECT.md": _manifest("delivery_profile: nope\n")})
    result = check_profile_declared(repo, registered_profiles=REGISTERED)
    assert result["status"] == "violation"


def test_profile_registered_passes(make_repo):
    repo = make_repo("x", files={"PROJECT.md": _manifest("delivery_profile: software-delivery\n")})
    assert check_profile_declared(repo, registered_profiles=REGISTERED)["status"] == "pass"


def test_profile_no_manifest_fires(make_repo):
    repo = make_repo("x")
    assert check_profile_declared(repo, registered_profiles=REGISTERED)["status"] == "violation"


def test_registered_profiles_unavailable_is_unknown(make_repo):
    repo = make_repo("x", files={"PROJECT.md": _manifest("delivery_profile: software-delivery\n")})
    assert check_profile_declared(repo, registered_profiles=None)["status"] == "unknown"


def test_live_registered_profiles_parses_lines(monkeypatch):
    def fake_run(cmd, cwd=None, env=None, timeout=None):
        assert cmd[:3] == ["uv", "run", "--project"]
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="dependency-update\nsoftware-delivery\n"
        )

    monkeypatch.setattr(onboard_checks, "_run", fake_run)
    assert onboard_checks.registered_profiles() == ["dependency-update", "software-delivery"]


def test_live_registered_profiles_failure_returns_none(monkeypatch):
    monkeypatch.setattr(onboard_checks, "_run", lambda *a, **k: None)
    assert onboard_checks.registered_profiles() is None
