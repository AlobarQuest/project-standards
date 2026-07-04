from datetime import date

import pytest

from portfolio import exceptions
from portfolio.exceptions import expired, local_matches, validate_local

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


def test_load_exception_key_not_a_list_raises(tmp_path):
    p = tmp_path / "exceptions.toml"
    p.write_text("exception = 5\n")
    with pytest.raises(exceptions.ExceptionsError) as exc_info:
        exceptions.load(p)
    assert str(p) in str(exc_info.value)


def test_load_exception_list_with_non_table_raises(tmp_path):
    p = tmp_path / "exceptions.toml"
    p.write_text('exception = ["str"]\n')
    with pytest.raises(exceptions.ExceptionsError) as exc_info:
        exceptions.load(p)
    assert str(p) in str(exc_info.value)


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


def _entry(**over):
    base = {
        "standard": "code",
        "finding": "code.not-onboarded",
        "reason": "r",
        "added": "2026-07-03",
    }
    return {**base, **over}


def test_validate_local_accepts_and_normalizes_dates():
    valid, errors = validate_local([_entry(added=date(2026, 7, 3), review_by=date(2026, 9, 1))])
    assert errors == []
    assert valid[0]["added"] == "2026-07-03"
    assert valid[0]["review_by"] == "2026-09-01"


def test_validate_local_rejects_missing_fields_and_bad_standard():
    valid, errors = validate_local(
        [
            {"standard": "code"},  # missing finding/reason/added
            _entry(standard="nope"),
            "not-a-mapping",
        ]
    )
    assert valid == [] and len(errors) == 3


def test_validate_local_rejects_unparseable_review_by():
    valid, errors = validate_local([_entry(review_by="soonish")])
    assert valid == [] and errors


def test_local_matches_uses_fnmatch_and_standard():
    e = _entry(finding="code.*")
    assert local_matches(e, "code", "code.not-onboarded")
    assert not local_matches(e, "security", "code.not-onboarded")


def test_expired():
    assert not expired(_entry(), date(2026, 7, 3))  # no review_by
    assert not expired(_entry(review_by="2026-09-01"), date(2026, 9, 1))  # boundary: not yet
    assert expired(_entry(review_by="2026-09-01"), date(2026, 9, 2))
