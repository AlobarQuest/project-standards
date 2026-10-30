import subprocess
from pathlib import Path

import pytest

from portfolio import config
from portfolio.retired_hosts import scan
from portfolio.validator import lint

ADDRESS = "203.0.113.7"


@pytest.fixture
def hosts_file(tmp_path, monkeypatch):
    path = tmp_path / "retired-hosts.toml"
    path.write_text(
        f'[[host]]\naddress = "{ADDRESS}"\nlabel = "old VPS"\n'
        'replacement = "new VPS"\nretired = "2026-10-23"\n'
    )
    monkeypatch.setenv("RETIRED_HOSTS", str(path))
    return path


def _tracked_repo(tmp_path, files):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for name, text in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


def test_live_doc_naming_a_retired_host_warns(tmp_path, hosts_file):
    repo = _tracked_repo(tmp_path, {"RESTORE.md": f"ssh root@{ADDRESS}\n"})
    findings = scan(repo)
    assert [(f.severity, f.code) for f in findings] == [("WARN", "retired_host")]
    assert "RESTORE.md" in findings[0].message
    assert "new VPS" in findings[0].message


def test_untracked_file_is_ignored(tmp_path, hosts_file):
    repo = _tracked_repo(tmp_path, {"README.md": "clean\n"})
    (repo / "scratch.md").write_text(ADDRESS)
    assert scan(repo) == []


@pytest.mark.parametrize(
    "name",
    [
        "docs/superpowers/plans/old.md",
        "docs/decisions/0001.md",
        "docs/reports/move.md",
        "tests/test_x.py",
    ],
)
def test_historical_paths_keep_their_addresses(tmp_path, hosts_file, name):
    assert scan(_tracked_repo(tmp_path, {name: ADDRESS})) == []


def test_marker_exempts_a_dated_report(tmp_path, hosts_file):
    text = f"<!-- retired-hosts: historical -->\n{ADDRESS}\n"
    assert scan(_tracked_repo(tmp_path, {"SECURITY_REVIEW.md": text})) == []


def test_unreadable_list_warns_instead_of_reporting_clean(tmp_path, hosts_file):
    hosts_file.write_text("[[host]\n")
    findings = scan(_tracked_repo(tmp_path, {"README.md": ADDRESS}))
    assert [f.code for f in findings] == ["retired_host_unmeasured"]


def test_entry_missing_a_field_warns(tmp_path, hosts_file):
    hosts_file.write_text(f'[[host]]\naddress = "{ADDRESS}"\n')
    findings = scan(_tracked_repo(tmp_path, {"README.md": ADDRESS}))
    assert [f.code for f in findings] == ["retired_host_unmeasured"]


def test_missing_list_warns_instead_of_reporting_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("RETIRED_HOSTS", str(tmp_path / "absent.toml"))
    findings = scan(_tracked_repo(tmp_path, {"README.md": ADDRESS}))
    assert [f.code for f in findings] == ["retired_host_unmeasured"]


def test_single_table_instead_of_list_warns(tmp_path, hosts_file):
    hosts_file.write_text(f'[host]\naddress = "{ADDRESS}"\n')
    findings = scan(_tracked_repo(tmp_path, {"README.md": ADDRESS}))
    assert [f.code for f in findings] == ["retired_host_unmeasured"]


def test_shipped_list_does_not_flag_itself():
    assert scan(Path(__file__).resolve().parents[1]) == []


def test_lint_reports_retired_hosts_without_failing(tmp_path, hosts_file):
    repo = _tracked_repo(tmp_path, {"PROJECT.md": "---\nname: repo\n---\n", "DEPLOY.md": ADDRESS})
    retired = [f for f in lint(repo) if f.code == "retired_host"]
    assert [f.severity for f in retired] == ["WARN"]


def test_shipped_list_loads():
    from portfolio.retired_hosts import load

    assert load(config.retired_hosts_path())
