import json
from datetime import datetime

import pytest

from portfolio import config, checkers, exceptions
from portfolio.foundation import FoundationError, run_foundation
from portfolio.matrix import CheckResult, PASS, VIOLATION, NA


NOW = datetime(2026, 7, 2, 12, 0, 0)


def _manifest(applicable=None, foundation_flag=True, coolify=None, name="x"):
    lines = [
        "---",
        f"name: {name}",
        "tier: active",
        "status: active",
        "version: 1.0.0",
        "version_source: package.json",
        "purpose: p",
        "updated: 2026-06-25",
        f"foundation: {'true' if foundation_flag else 'false'}",
    ]
    if applicable is not None:
        lines.append("applicable_standards:")
        for s in applicable:
            lines.append(f"  - {s}")
    if coolify is not None:
        lines.append("coolify_resources:")
        for c in coolify:
            lines.append(f'  - "{c}"')
    lines += ["---", "", "## Backlog", ""]
    return "\n".join(lines) + "\n"


def _stub_governance_pass(monkeypatch):
    monkeypatch.setattr(checkers, "check_governance", lambda: CheckResult("governance", PASS))


def test_single_foundational_repo_only_project_applicable(monkeypatch, make_repo, portfolio_env):
    _stub_governance_pass(monkeypatch)
    make_repo("a", files={"PROJECT.md": _manifest(["project"], name="a")})
    make_repo("b", files={"PROJECT.md": _manifest(None, foundation_flag=False, name="b")})

    report = run_foundation(roots=[portfolio_env.parent], now=NOW)

    assert len(report["repos"]) == 1
    row = report["repos"][0]
    assert row["repo"] == "a"
    assert row["cells"]["security"]["status"] == NA
    assert row["cells"]["code"]["status"] == NA
    assert row["cells"]["infra"]["status"] == NA
    assert row["cells"]["project"]["status"] == PASS
    assert report["exit_code"] == 0

    assert config.foundation_json_path().exists()
    assert config.foundation_digest_path().exists()
    on_disk = json.loads(config.foundation_json_path().read_text())
    assert on_disk == report


def test_security_violation_drives_exit_code_1(monkeypatch, make_repo, portfolio_env):
    _stub_governance_pass(monkeypatch)

    def fake_check_security(repo):
        return CheckResult("security", VIOLATION,
                            details=[{"id": "security.101:abc", "message": "bad thing"}])

    monkeypatch.setattr(checkers, "check_security", fake_check_security)
    make_repo("x", files={"PROJECT.md": _manifest(["project", "security"])})

    report = run_foundation(roots=[portfolio_env.parent], now=NOW)

    row = report["repos"][0]
    assert row["cells"]["security"]["status"] == VIOLATION
    assert report["exit_code"] == 1


def test_exceptions_cover_violation_and_unused_entry_reported(monkeypatch, make_repo, portfolio_env, tmp_path):
    _stub_governance_pass(monkeypatch)

    def fake_check_security(repo):
        return CheckResult("security", VIOLATION,
                            details=[{"id": "security.101:abc", "message": "bad thing"}])

    monkeypatch.setattr(checkers, "check_security", fake_check_security)
    make_repo("x", files={"PROJECT.md": _manifest(["project", "security"])})

    exc_path = tmp_path / "foundation-exceptions.toml"
    exc_path.write_text(
        "[[exception]]\n"
        'repo = "x"\n'
        'standard = "security"\n'
        'finding = "security.101:*"\n'
        'reason = "known false positive"\n'
        'added = "2026-07-01"\n'
        "\n"
        "[[exception]]\n"
        'repo = "unrelated"\n'
        'standard = "security"\n'
        'finding = "security.999:*"\n'
        'reason = "never matched"\n'
        'added = "2026-07-01"\n'
    )
    monkeypatch.setenv("FOUNDATION_EXCEPTIONS", str(exc_path))

    report = run_foundation(roots=[portfolio_env.parent], now=NOW)

    row = report["repos"][0]
    assert row["cells"]["security"]["status"] == "accepted-exception"
    assert report["exit_code"] == 0
    assert len(report["unused_exceptions"]) == 1
    assert report["unused_exceptions"][0]["repo"] == "unrelated"


def test_infra_batch_wiring_and_resolve(monkeypatch, make_repo, portfolio_env):
    _stub_governance_pass(monkeypatch)

    def fake_check_infra(repo_resources, now):
        assert repo_resources == {"x": ["x"]}
        return {"x": CheckResult("infra", VIOLATION,
                                  details=[{"id": "572:aaa", "message": "drift"}])}

    monkeypatch.setattr(checkers, "check_infra", fake_check_infra)
    make_repo("x", files={"PROJECT.md": _manifest(["project", "infra"], coolify=["x"])})

    report = run_foundation(roots=[portfolio_env.parent], now=NOW)

    row = report["repos"][0]
    assert row["cells"]["infra"]["status"] == VIOLATION
    assert row["cells"]["infra"]["details"][0]["id"] == "572:aaa"


def test_infra_exception_used_not_reported_as_unused(monkeypatch, make_repo, portfolio_env, tmp_path):
    _stub_governance_pass(monkeypatch)

    def fake_check_infra(repo_resources, now):
        assert repo_resources == {"x": ["x"]}
        return {"x": CheckResult("infra", VIOLATION,
                                  details=[{"id": "572:abc", "message": "drift"}])}

    monkeypatch.setattr(checkers, "check_infra", fake_check_infra)
    make_repo("x", files={"PROJECT.md": _manifest(["project", "infra"], coolify=["x"])})

    exc_path = tmp_path / "foundation-exceptions.toml"
    exc_path.write_text(
        "[[exception]]\n"
        'repo = "x"\n'
        'standard = "infra"\n'
        'finding = "572:*"\n'
        'reason = "known infra drift"\n'
        'added = "2026-07-01"\n'
    )
    monkeypatch.setenv("FOUNDATION_EXCEPTIONS", str(exc_path))

    report = run_foundation(roots=[portfolio_env.parent], now=NOW)

    row = report["repos"][0]
    assert row["cells"]["infra"]["status"] == "accepted-exception"
    assert report["unused_exceptions"] == []


def test_no_foundational_repos_raises(monkeypatch, make_repo, portfolio_env):
    _stub_governance_pass(monkeypatch)
    make_repo("a", files={"PROJECT.md": _manifest(None, foundation_flag=False, name="a")})

    with pytest.raises(FoundationError):
        run_foundation(roots=[portfolio_env.parent], now=NOW)


def test_malformed_exceptions_file_propagates(monkeypatch, portfolio_env, tmp_path):
    bad_path = tmp_path / "bad-exceptions.toml"
    bad_path.write_bytes(b"\x00\x01 not = valid [[[ toml")
    monkeypatch.setenv("FOUNDATION_EXCEPTIONS", str(bad_path))

    with pytest.raises(exceptions.ExceptionsError):
        run_foundation(roots=[portfolio_env.parent], now=NOW)


_FAKE_CLI = '''
import json
import sys


def main():
    payload = {
        "meta": {},
        "summary": {"by_severity": {"BLOCK": 1, "WARN": 0, "NOTE": 0}, "total": 1},
        "findings": [{
            "rule_id": "secrets.bws_token",
            "severity": "BLOCK",
            "file": "config.py",
            "line": 12,
            "evidence": "...",
            "remediation": "...",
            "reason": "committed BWS token",
            "kind": "regex",
        }],
        "allowlisted": [],
    }
    print(json.dumps(payload))
    sys.exit(1)


if __name__ == "__main__":
    main()
'''


def test_integration_real_subprocess_security_path(monkeypatch, make_repo, portfolio_env, tmp_path):
    _stub_governance_pass(monkeypatch)

    fake_security_repo = tmp_path / "fake-security-standards"
    pkg_dir = fake_security_repo / "src" / "security_scan"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "cli.py").write_text(_FAKE_CLI)

    monkeypatch.setenv("SECURITY_STANDARDS_REPO", str(fake_security_repo))
    make_repo("x", files={"PROJECT.md": _manifest(["security"])})

    report = run_foundation(roots=[portfolio_env.parent], now=NOW)

    row = report["repos"][0]
    assert row["cells"]["security"]["status"] == VIOLATION
    assert row["cells"]["security"]["details"][0]["id"] == "security.secrets.bws_token"
