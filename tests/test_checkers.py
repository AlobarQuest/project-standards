import json
import subprocess

from portfolio import checkers, config
from portfolio.checkers import _run, check_project, check_security, check_code
from portfolio.matrix import PASS, VIOLATION, UNKNOWN


def _good_active():
    return ("---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\n"
            "version_source: package.json\npurpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n")


def _good_parking():
    return "---\nname: x\ntier: parking\nstatus: idea\npurpose: p\n---\n\n## Backlog\n"


def test_run_returns_completed_process_on_nonzero_exit():
    result = _run(["false"])
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.returncode == 1


def test_run_returns_none_on_missing_command():
    assert _run(["definitely-not-a-command-xyz"]) is None


def test_check_project_missing_manifest_is_violation(make_repo):
    repo = make_repo("x")
    result = check_project(repo)
    assert result.standard == "project"
    assert result.status == VIOLATION
    assert any(d["id"] == "project.missing_manifest" for d in result.details)


def test_check_project_valid_active_repo_is_pass(make_repo):
    repo = make_repo("x", files={"PROJECT.md": _good_active(), "package.json": '{"version":"1.0.0"}'})
    result = check_project(repo)
    assert result.status == PASS
    assert all(not d["id"].endswith("missing_manifest") for d in result.details)


def test_check_project_parking_non_git_is_pass_with_warn_detail(make_repo):
    repo = make_repo("x", git=False, files={"PROJECT.md": _good_parking()})
    result = check_project(repo)
    assert result.status == PASS
    assert any(d["id"] == "project.not_git" for d in result.details)


def _scan_payload(by_severity, findings):
    return json.dumps({
        "meta": {},
        "summary": {"by_severity": by_severity, "total": sum(by_severity.values())},
        "findings": findings,
        "allowlisted": [],
    })


def test_check_security_block_finding_is_violation(monkeypatch, make_repo, tmp_path):
    repo = make_repo("x")
    fake_src_repo = tmp_path / "security-standards"
    monkeypatch.setenv("SECURITY_STANDARDS_REPO", str(fake_src_repo))

    captured = {}
    finding = {
        "rule_id": "secrets.bws_token", "severity": "BLOCK", "file": "config.py",
        "line": 12, "evidence": "...", "remediation": "...", "reason": "committed BWS token",
        "kind": "regex",
    }

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        captured["cmd"] = cmd
        captured["env"] = env
        return subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout=_scan_payload({"BLOCK": 1, "WARN": 0, "NOTE": 0}, [finding]),
            stderr="",
        )

    monkeypatch.setattr(checkers, "_run", fake_run)
    result = check_security(repo)

    assert result.status == VIOLATION
    assert len(result.details) == 1
    assert result.details[0]["id"] == "security.secrets.bws_token"
    assert result.details[0]["message"] == "config.py:12 committed BWS token"

    cmd = captured["cmd"]
    assert "-m" in cmd
    assert "security_scan.cli" in cmd
    assert captured["env"]["PYTHONPATH"].endswith("security-standards/src")


def test_check_security_no_block_findings_is_pass_with_warn_detail(monkeypatch, make_repo, tmp_path):
    repo = make_repo("x")
    monkeypatch.setenv("SECURITY_STANDARDS_REPO", str(tmp_path / "security-standards"))
    finding = {
        "rule_id": "secrets.weak_pattern", "severity": "WARN", "file": "app.py",
        "line": 5, "evidence": "...", "remediation": "...", "reason": "possible weak pattern",
        "kind": "regex",
    }

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        return subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=_scan_payload({"BLOCK": 0, "WARN": 1, "NOTE": 0}, [finding]),
            stderr="",
        )

    monkeypatch.setattr(checkers, "_run", fake_run)
    result = check_security(repo)

    assert result.status == PASS
    assert len(result.details) == 1
    assert result.details[0]["id"] == "security.secrets.weak_pattern"
    assert result.details[0]["message"] == "app.py:5 possible weak pattern"


def test_check_security_run_unavailable_is_unknown(monkeypatch, make_repo):
    repo = make_repo("x")
    monkeypatch.setattr(checkers, "_run", lambda *a, **k: None)
    result = check_security(repo)
    assert result.status == UNKNOWN
    assert "unavailable" in result.note


def test_check_security_unparseable_stdout_is_unknown(monkeypatch, make_repo):
    repo = make_repo("x")

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="not json{", stderr="")

    monkeypatch.setattr(checkers, "_run", fake_run)
    result = check_security(repo)
    assert result.status == UNKNOWN
    assert "unreadable" in result.note


def test_check_security_missing_summary_key_is_unknown(monkeypatch, make_repo):
    repo = make_repo("x")

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps({"meta": {}}), stderr="")

    monkeypatch.setattr(checkers, "_run", fake_run)
    result = check_security(repo)
    assert result.status == UNKNOWN


def _run_returning(stdout):
    def fake_run(cmd, cwd=None, env=None, timeout=None):
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")
    return fake_run


def test_check_security_non_dict_json_payload_is_unknown(monkeypatch, make_repo):
    repo = make_repo("x")
    monkeypatch.setattr(checkers, "_run", _run_returning(json.dumps([1, 2, 3])))
    result = check_security(repo)
    assert result.status == UNKNOWN
    assert "unreadable" in result.note


def test_check_security_non_dict_summary_is_unknown(monkeypatch, make_repo):
    repo = make_repo("x")
    monkeypatch.setattr(checkers, "_run", _run_returning(json.dumps({"summary": "nope"})))
    result = check_security(repo)
    assert result.status == UNKNOWN
    assert "unreadable" in result.note


def test_check_security_non_dict_by_severity_is_unknown(monkeypatch, make_repo):
    repo = make_repo("x")
    monkeypatch.setattr(checkers, "_run",
                        _run_returning(json.dumps({"summary": {"by_severity": "nope"}})))
    result = check_security(repo)
    assert result.status == UNKNOWN
    assert "unreadable" in result.note


def test_check_security_block_finding_null_line_renders_dash(monkeypatch, make_repo):
    repo = make_repo("x")
    finding = {
        "rule_id": "manifest.drift", "severity": "BLOCK", "file": ".bws-secrets.toml",
        "line": None, "evidence": "...", "remediation": "...", "reason": "manifest drift",
        "kind": "manifest",
    }
    monkeypatch.setattr(
        checkers, "_run",
        _run_returning(_scan_payload({"BLOCK": 1, "WARN": 0, "NOTE": 0}, [finding])))
    result = check_security(repo)
    assert result.status == VIOLATION
    assert result.details[0]["message"] == ".bws-secrets.toml:- manifest drift"


def _raise_if_called(*a, **k):
    raise AssertionError("_run must not be called for a not-onboarded repo")


def test_check_code_not_onboarded_is_violation_without_invoking_run(monkeypatch, make_repo):
    repo = make_repo("x")
    monkeypatch.setattr(checkers, "_run", _raise_if_called)
    result = check_code(repo)
    assert result.standard == "code"
    assert result.status == VIOLATION
    assert any(d["id"] == "code.not-onboarded" for d in result.details)


def test_check_code_onboarded_clean_is_pass(monkeypatch, make_repo):
    repo = make_repo("x", files={".code-standards.toml": ""})

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(checkers, "_run", fake_run)
    result = check_code(repo)
    assert result.status == PASS
    assert result.details == []


def test_check_code_violations_parsed_from_stdout(monkeypatch, make_repo):
    repo = make_repo("x", files={".code-standards.toml": ""})

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout="a.py:3 ruff-E501 line too long\n", stderr="")

    monkeypatch.setattr(checkers, "_run", fake_run)
    result = check_code(repo)
    assert result.status == VIOLATION
    assert len(result.details) == 1
    assert result.details[0]["id"] == "code.ruff-E501"
    assert "a.py:3" in result.details[0]["message"]


def test_check_code_unparseable_line_gets_generic_id(monkeypatch, make_repo):
    repo = make_repo("x", files={".code-standards.toml": ""})

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        return subprocess.CompletedProcess(args=[], returncode=1, stdout="oops\n", stderr="")

    monkeypatch.setattr(checkers, "_run", fake_run)
    result = check_code(repo)
    assert result.status == VIOLATION
    assert result.details[0]["id"] == "code.violation"


def test_check_code_could_not_run_is_unknown(monkeypatch, make_repo):
    repo = make_repo("x", files={".code-standards.toml": ""})

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        return subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr="boom\n")

    monkeypatch.setattr(checkers, "_run", fake_run)
    result = check_code(repo)
    assert result.status == UNKNOWN
    assert "could not run" in result.note
    assert "boom" in result.note


def test_check_code_run_unavailable_is_unknown(monkeypatch, make_repo):
    repo = make_repo("x", files={".code-standards.toml": ""})
    monkeypatch.setattr(checkers, "_run", lambda *a, **k: None)
    result = check_code(repo)
    assert result.status == UNKNOWN
    assert "unavailable" in result.note


def test_check_code_cmd_construction(monkeypatch, make_repo):
    repo = make_repo("x", files={".code-standards.toml": ""})
    captured = {}

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    monkeypatch.setattr(checkers, "_run", fake_run)
    check_code(repo)

    assert "check" in checkers._code_cmd()
    assert captured["cmd"][-2:] == ["--repo", str(repo)]
    assert captured["cwd"] == config.code_standards_repo()
