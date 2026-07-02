import json
import subprocess
from datetime import datetime, timedelta, timezone

from portfolio import checkers, config
from portfolio.checkers import _run, check_project, check_security, check_code, check_governance, check_infra
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


def test_check_governance_rc_zero_is_pass(monkeypatch, tmp_path):
    fake_src_repo = tmp_path / "security-standards"
    monkeypatch.setenv("SECURITY_STANDARDS_REPO", str(fake_src_repo))
    captured = {}

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        captured["env"] = env
        return subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="governance verify: artifacts + headers + ownership in sync",
            stderr="",
        )

    monkeypatch.setattr(checkers, "_run", fake_run)
    result = check_governance()

    assert result.standard == "governance"
    assert result.status == PASS
    assert "security_scan.governance" in captured["cmd"]
    assert "verify" in captured["cmd"]
    assert captured["cwd"] == config.security_standards_repo()
    assert captured["env"]["PYTHONPATH"].endswith("security-standards/src")


def test_check_governance_rc_one_is_violation_with_details(monkeypatch, tmp_path):
    fake_src_repo = tmp_path / "security-standards"
    monkeypatch.setenv("SECURITY_STANDARDS_REPO", str(fake_src_repo))

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        return subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="artifact hook: bws-write-guard.sh\nownership stale: OWNERSHIP.md",
            stderr="",
        )

    monkeypatch.setattr(checkers, "_run", fake_run)
    result = check_governance()

    assert result.standard == "governance"
    assert result.status == VIOLATION
    assert len(result.details) == 2
    assert result.details[0]["id"] == "governance.artifact"
    assert result.details[0]["message"] == "artifact hook: bws-write-guard.sh"
    assert result.details[1]["id"] == "governance.ownership"
    assert result.details[1]["message"] == "ownership stale: OWNERSHIP.md"


def test_check_governance_rc_three_is_unknown_with_rc_in_note(monkeypatch, tmp_path):
    fake_src_repo = tmp_path / "security-standards"
    monkeypatch.setenv("SECURITY_STANDARDS_REPO", str(fake_src_repo))

    def fake_run(cmd, cwd=None, env=None, timeout=None):
        return subprocess.CompletedProcess(
            args=[], returncode=3, stdout="", stderr="something went wrong\n",
        )

    monkeypatch.setattr(checkers, "_run", fake_run)
    result = check_governance()

    assert result.standard == "governance"
    assert result.status == UNKNOWN
    assert "3" in result.note
    assert "something went wrong" in result.note


def test_check_governance_run_unavailable_is_unknown(monkeypatch, tmp_path):
    fake_src_repo = tmp_path / "security-standards"
    monkeypatch.setenv("SECURITY_STANDARDS_REPO", str(fake_src_repo))
    monkeypatch.setattr(checkers, "_run", lambda *a, **k: None)
    result = check_governance()

    assert result.standard == "governance"
    assert result.status == UNKNOWN
    assert "unavailable" in result.note


# --- check_infra ---------------------------------------------------------

def _report_payload(generated_at="2026-07-02T07:00:05Z", instances=None):
    return {
        "generated_at": generated_at,
        "instances": instances if instances is not None else {
            "prod": {"ok": True, "standards_source": "s", "summary": {}, "proposals": []},
        },
        "totals": {},
        "delta": {},
    }


def _write_report(report_dir, name, payload):
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / name).write_text(json.dumps(payload))
    return report_dir / name


def _now_for(generated_at="2026-07-02T07:00:05Z", plus_hours=1):
    dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
    return dt + timedelta(hours=plus_hours)


def test_check_infra_violation_by_name_match_prefers_description(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    proposal = {
        "id": "572:bd9d2439",
        "target": {"provider": "coolify", "resource_type": "application", "uuid": "u-1", "name": "myapp"},
        "description": "env var drift on myapp",
        "summary": "should not be used",
    }
    payload = _report_payload(instances={
        "prod": {"ok": True, "standards_source": "s", "summary": {}, "proposals": [proposal]},
    })
    _write_report(report_dir, "2026-07-02.json", payload)

    result = check_infra({"myapp-repo": ["myapp"]}, _now_for())

    assert result["myapp-repo"].standard == "infra"
    assert result["myapp-repo"].status == VIOLATION
    assert result["myapp-repo"].details == [{"id": "572:bd9d2439", "message": "env var drift on myapp"}]


def test_check_infra_violation_by_uuid_match(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    proposal = {
        "id": "572:bd9d2439",
        "target": {"provider": "coolify", "resource_type": "application", "uuid": "u-1", "name": "myapp"},
        "description": "env var drift on myapp",
    }
    payload = _report_payload(instances={
        "prod": {"ok": True, "standards_source": "s", "summary": {}, "proposals": [proposal]},
    })
    _write_report(report_dir, "2026-07-02.json", payload)

    result = check_infra({"myapp-repo": ["u-1"]}, _now_for())

    assert result["myapp-repo"].status == VIOLATION
    assert result["myapp-repo"].details[0]["id"] == "572:bd9d2439"


def test_check_infra_message_falls_back_to_summary(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    proposal = {
        "id": "572:bd9d2439",
        "target": {"uuid": "u-1", "name": "myapp"},
        "summary": "env var drift on myapp (summary)",
    }
    payload = _report_payload(instances={
        "prod": {"ok": True, "standards_source": "s", "summary": {}, "proposals": [proposal]},
    })
    _write_report(report_dir, "2026-07-02.json", payload)

    result = check_infra({"myapp-repo": ["myapp"]}, _now_for())

    assert result["myapp-repo"].details[0]["message"] == "env var drift on myapp (summary)"


def test_check_infra_no_matching_proposals_is_pass_with_report_name_in_note(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    _write_report(report_dir, "2026-07-02.json", _report_payload())

    result = check_infra({"myapp-repo": ["some-other-uuid"]}, _now_for())

    assert result["myapp-repo"].status == PASS
    assert "2026-07-02.json" in result["myapp-repo"].note


def test_check_infra_stale_report_is_all_unknown(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    _write_report(report_dir, "2026-07-02.json", _report_payload())

    now = _now_for(plus_hours=40)
    result = check_infra({"a": ["x"], "b": []}, now)

    assert result["a"].status == UNKNOWN
    assert "stale" in result["a"].note
    assert "2026-07-02.json" in result["a"].note
    assert result["b"].status == UNKNOWN


def test_check_infra_empty_dir_is_all_unknown_no_report(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True)
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))

    result = check_infra({"a": ["x"]}, datetime.now(timezone.utc))

    assert result["a"].status == UNKNOWN
    assert "no infra drift report" in result["a"].note


def test_check_infra_missing_dir_is_all_unknown_no_report(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"  # never created
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))

    result = check_infra({"a": ["x"]}, datetime.now(timezone.utc))

    assert result["a"].status == UNKNOWN
    assert "no infra drift report" in result["a"].note


def test_check_infra_instance_not_ok_is_all_unknown_naming_prod(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    payload = _report_payload(instances={
        "prod": {"ok": False, "standards_source": "s", "summary": {}, "proposals": []},
        "dev": {"ok": True, "standards_source": "s", "summary": {}, "proposals": []},
    })
    _write_report(report_dir, "2026-07-02.json", payload)

    result = check_infra({"a": ["x"]}, _now_for())

    assert result["a"].status == UNKNOWN
    assert "prod" in result["a"].note


def test_check_infra_empty_resource_list_is_unknown(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    _write_report(report_dir, "2026-07-02.json", _report_payload())

    result = check_infra({"a": []}, _now_for())

    assert result["a"].status == UNKNOWN
    assert "coolify_resources" in result["a"].note


def test_check_infra_only_remediation_file_is_treated_as_no_report(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    _write_report(report_dir, "2026-07-02.remediation.json", _report_payload())

    result = check_infra({"a": ["x"]}, _now_for())

    assert result["a"].status == UNKNOWN
    assert "no infra drift report" in result["a"].note


def test_check_infra_two_date_files_uses_newer(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))

    old_proposal = {"id": "1:aaa", "target": {"uuid": "u-1", "name": "old-app"}, "description": "old drift"}
    new_proposal = {"id": "2:bbb", "target": {"uuid": "u-2", "name": "new-app"}, "description": "new drift"}

    _write_report(report_dir, "2026-07-01.json", _report_payload(
        generated_at="2026-07-01T07:00:05Z",
        instances={"prod": {"ok": True, "standards_source": "s", "summary": {}, "proposals": [old_proposal]}},
    ))
    _write_report(report_dir, "2026-07-02.json", _report_payload(
        generated_at="2026-07-02T07:00:05Z",
        instances={"prod": {"ok": True, "standards_source": "s", "summary": {}, "proposals": [new_proposal]}},
    ))

    now = _now_for(generated_at="2026-07-02T07:00:05Z")
    result = check_infra({"repo": ["new-app", "old-app"]}, now)

    assert result["repo"].status == VIOLATION
    ids = [d["id"] for d in result["repo"].details]
    assert ids == ["2:bbb"]


def test_check_infra_garbage_json_is_unknown_unreadable(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir(parents=True)
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    (report_dir / "2026-07-02.json").write_text("{not valid json")

    result = check_infra({"a": ["x"]}, _now_for())

    assert result["a"].status == UNKNOWN
    assert "unreadable" in result["a"].note


def test_check_infra_missing_generated_at_is_unknown_unreadable(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    _write_report(report_dir, "2026-07-02.json", {"instances": {}})

    result = check_infra({"a": ["x"]}, _now_for())

    assert result["a"].status == UNKNOWN
    assert "unreadable" in result["a"].note


def test_check_infra_null_proposals_is_all_unknown_naming_instance(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    payload = _report_payload(instances={
        "prod": {"ok": True, "standards_source": "s", "summary": {}, "proposals": None},
        "dev": {"ok": True, "standards_source": "s", "summary": {}, "proposals": []},
    })
    _write_report(report_dir, "2026-07-02.json", payload)

    result = check_infra({"a": ["x"]}, _now_for())

    assert result["a"].status == UNKNOWN
    assert "prod" in result["a"].note


def test_check_infra_non_list_proposals_is_all_unknown_naming_instance(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    payload = _report_payload(instances={
        "prod": {"ok": True, "standards_source": "s", "summary": {}, "proposals": {"oops": 1}},
    })
    _write_report(report_dir, "2026-07-02.json", payload)

    result = check_infra({"a": ["x"]}, _now_for())

    assert result["a"].status == UNKNOWN
    assert "prod" in result["a"].note


def test_check_infra_proposal_message_never_none(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(report_dir))
    proposal = {"id": None, "target": {"uuid": "u-1", "name": "myapp"}}
    payload = _report_payload(instances={
        "prod": {"ok": True, "standards_source": "s", "summary": {}, "proposals": [proposal]},
    })
    _write_report(report_dir, "2026-07-02.json", payload)

    result = check_infra({"a": ["myapp"]}, _now_for())

    assert result["a"].status == VIOLATION
    assert result["a"].details[0]["message"] == "(no description)"
