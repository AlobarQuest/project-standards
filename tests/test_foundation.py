import json
from datetime import datetime

import pytest

from portfolio import checkers, config, exceptions
from portfolio.foundation import FoundationError, run_foundation
from portfolio.matrix import NA, PASS, VIOLATION, CheckResult

NOW = datetime(2026, 7, 2, 12, 0, 0)


def _manifest(
    applicable=None,
    foundation_flag=True,
    coolify=None,
    name="x",
    required_checks=True,
    exceptions_fm=None,
):
    lines = [
        "---",
        f"name: {name}",
        "tier: active",
        "status: active",
        "version: 1.0.0",
        "version_source: package.json",
        "purpose: p",
        "updated: '2026-06-25'",
        f"foundation: {'true' if foundation_flag else 'false'}",
    ]
    if applicable is not None:
        lines.append("applicable_standards:")
        for s in applicable:
            lines.append(f"  {s}: '1.0'")
    if coolify is not None:
        lines.append("coolify_resources:")
        for c in coolify:
            lines.append(f'  - "{c}"')
    if required_checks:
        lines.append("required_checks:")
        lines.append("- id: quality")
        lines.append("  executor: github-actions:quality.yml")
    if exceptions_fm:
        lines.append("exceptions:")
        for e in exceptions_fm:
            lines.append(f"- standard: {e['standard']}")
            lines.append(f"  finding: {e['finding']}")
            lines.append(f"  reason: {e['reason']}")
            lines.append(f"  added: '{e['added']}'")
    lines += ["---", "", "## Backlog", ""]
    return "\n".join(lines) + "\n"


def _repo_files(applicable=None, required_checks=True, **manifest_kwargs):
    """PROJECT.md (+ a wired quality.yml workflow, so the mandatory `checks`
    column never turns an unrelated fixture into a surprise violation)."""
    files = {
        "PROJECT.md": _manifest(applicable, required_checks=required_checks, **manifest_kwargs)
    }
    if required_checks:
        files[".github/workflows/quality.yml"] = "jobs:\n  quality: {}\n"
    return files


def _stub_governance_pass(monkeypatch):
    monkeypatch.setattr(checkers, "check_governance", lambda: CheckResult("governance", PASS))


def test_single_foundational_repo_only_project_applicable(
    monkeypatch, make_repo, portfolio_env, standards_env
):
    _stub_governance_pass(monkeypatch)
    make_repo("a", files=_repo_files(["project"], name="a"))
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


def test_security_violation_drives_exit_code_1(
    monkeypatch, make_repo, portfolio_env, standards_env
):
    _stub_governance_pass(monkeypatch)

    def fake_check_security(repo):
        return CheckResult(
            "security", VIOLATION, details=[{"id": "security.101:abc", "message": "bad thing"}]
        )

    monkeypatch.setattr(checkers, "check_security", fake_check_security)
    make_repo("x", files=_repo_files(["project", "security"]))

    report = run_foundation(roots=[portfolio_env.parent], now=NOW)

    row = report["repos"][0]
    assert row["cells"]["security"]["status"] == VIOLATION
    assert report["exit_code"] == 1


def test_frontmatter_exception_covers_violation_and_stale_entry_reported(
    monkeypatch, make_repo, portfolio_env, standards_env
):
    """Repo-scoped exceptions now live in the repo's own PROJECT.md frontmatter
    (WS-1.3) — the central foundation-exceptions.toml only ever resolves the
    `_machine` governance scope. An entry that never matches shows up in the
    per-repo `stale_repo_exceptions`, not the central `unused_exceptions`."""
    _stub_governance_pass(monkeypatch)

    def fake_check_security(repo):
        return CheckResult(
            "security", VIOLATION, details=[{"id": "security.101:abc", "message": "bad thing"}]
        )

    monkeypatch.setattr(checkers, "check_security", fake_check_security)
    repo = make_repo(
        "x",
        files=_repo_files(
            ["project", "security"],
            exceptions_fm=[
                {
                    "standard": "security",
                    "finding": "security.101:*",
                    "reason": "known false positive",
                    "added": "2026-07-01",
                },
                {
                    "standard": "security",
                    "finding": "security.999:*",
                    "reason": "never matched",
                    "added": "2026-07-01",
                },
            ],
        ),
    )

    report = run_foundation(roots=[portfolio_env.parent], now=NOW)

    row = report["repos"][0]
    assert row["cells"]["security"]["status"] == "accepted-exception"
    assert report["exit_code"] == 0
    assert report["unused_exceptions"] == []
    assert [e["reason"] for e in report["stale_repo_exceptions"][str(repo.resolve())]] == [
        "never matched"
    ]


def test_infra_batch_wiring_and_resolve(monkeypatch, make_repo, portfolio_env, standards_env):
    _stub_governance_pass(monkeypatch)

    def fake_check_infra(repo_resources, now):
        assert len(repo_resources) == 1
        path = next(iter(repo_resources))
        assert repo_resources[path] == ["x"]
        return {
            path: CheckResult("infra", VIOLATION, details=[{"id": "572:aaa", "message": "drift"}])
        }

    monkeypatch.setattr(checkers, "check_infra", fake_check_infra)
    make_repo("x", files=_repo_files(["project", "infra"], coolify=["x"]))

    report = run_foundation(roots=[portfolio_env.parent], now=NOW)

    row = report["repos"][0]
    assert row["cells"]["infra"]["status"] == VIOLATION
    assert row["cells"]["infra"]["details"][0]["id"] == "572:aaa"


def test_infra_frontmatter_exception_used_not_reported_as_stale(
    monkeypatch, make_repo, portfolio_env, standards_env
):
    _stub_governance_pass(monkeypatch)

    def fake_check_infra(repo_resources, now):
        assert len(repo_resources) == 1
        path = next(iter(repo_resources))
        assert repo_resources[path] == ["x"]
        return {
            path: CheckResult("infra", VIOLATION, details=[{"id": "572:abc", "message": "drift"}])
        }

    monkeypatch.setattr(checkers, "check_infra", fake_check_infra)
    make_repo(
        "x",
        files=_repo_files(
            ["project", "infra"],
            coolify=["x"],
            exceptions_fm=[
                {
                    "standard": "infra",
                    "finding": "572:*",
                    "reason": "known infra drift",
                    "added": "2026-07-01",
                }
            ],
        ),
    )

    report = run_foundation(roots=[portfolio_env.parent], now=NOW)

    row = report["repos"][0]
    assert row["cells"]["infra"]["status"] == "accepted-exception"
    assert report["unused_exceptions"] == []
    assert report["stale_repo_exceptions"] == {}


def test_no_foundational_repos_raises(monkeypatch, make_repo, portfolio_env, standards_env):
    _stub_governance_pass(monkeypatch)
    make_repo("a", files={"PROJECT.md": _manifest(None, foundation_flag=False, name="a")})

    with pytest.raises(FoundationError):
        run_foundation(roots=[portfolio_env.parent], now=NOW)


def test_malformed_exceptions_file_propagates(monkeypatch, portfolio_env, tmp_path, standards_env):
    bad_path = tmp_path / "bad-exceptions.toml"
    bad_path.write_bytes(b"\x00\x01 not = valid [[[ toml")
    monkeypatch.setenv("FOUNDATION_EXCEPTIONS", str(bad_path))

    with pytest.raises(exceptions.ExceptionsError):
        run_foundation(roots=[portfolio_env.parent], now=NOW)


_FAKE_CLI = """
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
"""


def test_integration_real_subprocess_security_path(
    monkeypatch, make_repo, portfolio_env, tmp_path, standards_env
):
    _stub_governance_pass(monkeypatch)

    fake_security_repo = tmp_path / "fake-security-standards"
    pkg_dir = fake_security_repo / "src" / "security_scan"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "cli.py").write_text(_FAKE_CLI)

    monkeypatch.setenv("SECURITY_STANDARDS_REPO", str(fake_security_repo))
    make_repo("x", files=_repo_files(["security"]))

    report = run_foundation(roots=[portfolio_env.parent], now=NOW)

    row = report["repos"][0]
    assert row["cells"]["security"]["status"] == VIOLATION
    assert row["cells"]["security"]["details"][0]["id"] == "security.secrets.bws_token"


def test_standard_version_bump_shows_drift_in_consumer(
    monkeypatch, make_repo, portfolio_env, standards_env
):
    repo = make_repo(
        "consumer",
        files={
            "PROJECT.md": (
                "---\nname: consumer\ntier: active\nstatus: active\nversion: 1.0\n"
                "version_source: none\npurpose: p\nupdated: '2026-07-03'\n"
                "foundation: true\nfoundation_contract: 1\n"
                "applicable_standards:\n  project: '1.0'\n"
                "required_checks:\n- id: quality\n  executor: github-actions:quality.yml\n"
                "---\n\n## Backlog\n"
            )
        },
    )
    wf = repo / ".github" / "workflows" / "quality.yml"
    wf.parent.mkdir(parents=True)
    wf.write_text("jobs:\n  quality: {}\n")
    monkeypatch.setattr(
        "portfolio.compliance.checkers.check_project", lambda r: CheckResult("project", PASS)
    )
    monkeypatch.setattr(
        "portfolio.checkers.check_governance", lambda: CheckResult("governance", PASS)
    )

    report = run_foundation(roots=[repo.parent])
    cell = report["repos"][0]["cells"]["project"]
    assert cell["status"] == PASS and report["exit_code"] == 0

    (standards_env["project"] / "STANDARD_VERSION").write_text("1.1\n")
    report = run_foundation(roots=[repo.parent])
    cell = report["repos"][0]["cells"]["project"]
    assert cell["status"] == VIOLATION
    assert any(d["id"] == "project.version-drift" for d in cell["details"])
    assert report["exit_code"] == 1
