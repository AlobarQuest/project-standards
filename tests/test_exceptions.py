from pathlib import Path
import pytest
from portfolio import exceptions

VALID_TOML = """\
[[exception]]
repo = "brain"
standard = "infra"
finding = "572:*"
reason = "backup config lands with BWS cutover"
added = "2026-07-02"
revisit = "when brain BWS cutover backlog item closes"

[[exception]]
repo = "crm"
standard = "security"
finding = "101:abc"
reason = "known false positive"
added = "2026-06-01"
"""

def test_load_valid_file_two_entries(tmp_path):
    p = tmp_path / "exceptions.toml"
    p.write_text(VALID_TOML)
    entries = exceptions.load(p)
    assert len(entries) == 2
    assert entries[0]["repo"] == "brain"
    assert entries[0]["standard"] == "infra"
    assert entries[0]["finding"] == "572:*"
    assert entries[0]["reason"] == "backup config lands with BWS cutover"
    assert entries[0]["added"] == "2026-07-02"
    assert entries[0]["revisit"] == "when brain BWS cutover backlog item closes"
    assert entries[1]["repo"] == "crm"

def test_load_missing_file_returns_empty(tmp_path):
    p = tmp_path / "does-not-exist.toml"
    assert exceptions.load(p) == []

def test_load_valid_toml_without_exception_key_returns_empty(tmp_path):
    p = tmp_path / "exceptions.toml"
    p.write_text('title = "no exceptions here"\n')
    assert exceptions.load(p) == []

def test_load_garbage_bytes_raises(tmp_path):
    p = tmp_path / "exceptions.toml"
    p.write_bytes(b"\x00\x01 not = valid [[[ toml")
    with pytest.raises(exceptions.ExceptionsError):
        exceptions.load(p)

def test_load_entry_missing_reason_raises(tmp_path):
    p = tmp_path / "exceptions.toml"
    p.write_text("""\
[[exception]]
repo = "brain"
standard = "infra"
finding = "572:*"
added = "2026-07-02"
""")
    with pytest.raises(exceptions.ExceptionsError) as exc_info:
        exceptions.load(p)
    msg = str(exc_info.value)
    assert "0" in msg
    assert "reason" in msg

def test_load_entry_empty_finding_raises(tmp_path):
    p = tmp_path / "exceptions.toml"
    p.write_text("""\
[[exception]]
repo = "brain"
standard = "infra"
finding = ""
reason = "some reason"
added = "2026-07-02"
""")
    with pytest.raises(exceptions.ExceptionsError) as exc_info:
        exceptions.load(p)
    assert "finding" in str(exc_info.value)

def test_load_entry_without_revisit_loads_fine(tmp_path):
    p = tmp_path / "exceptions.toml"
    p.write_text("""\
[[exception]]
repo = "brain"
standard = "infra"
finding = "572:*"
reason = "some reason"
added = "2026-07-02"
""")
    entries = exceptions.load(p)
    assert len(entries) == 1
    assert "revisit" not in entries[0] or entries[0].get("revisit") is None

def test_matches_exact_finding_id():
    entry = {"repo": "brain", "standard": "infra", "finding": "572:bd9d2439"}
    assert exceptions.matches(entry, "brain", "infra", "572:bd9d2439") is True

def test_matches_glob_finding():
    entry = {"repo": "brain", "standard": "infra", "finding": "572:*"}
    assert exceptions.matches(entry, "brain", "infra", "572:bd9d2439") is True

def test_matches_wrong_repo_false():
    entry = {"repo": "brain", "standard": "infra", "finding": "572:*"}
    assert exceptions.matches(entry, "crm", "infra", "572:bd9d2439") is False

def test_matches_wrong_standard_false():
    entry = {"repo": "brain", "standard": "infra", "finding": "572:*"}
    assert exceptions.matches(entry, "brain", "security", "572:bd9d2439") is False

def test_matches_glob_does_not_match_other_prefix():
    entry = {"repo": "brain", "standard": "infra", "finding": "572:*"}
    assert exceptions.matches(entry, "brain", "infra", "999:x") is False
