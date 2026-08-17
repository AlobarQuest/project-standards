import pytest

from portfolio.schema import validate_frontmatter


@pytest.fixture
def base_fm():
    return {
        "name": "x",
        "tier": "active",
        "status": "active",
        "version": "1.0",
        "version_source": "pyproject",
        "purpose": "p",
        "updated": "2026-07-03",
    }


def _codes(findings):
    return [f.code for f in findings]


def _active(**over):
    fm = {
        "name": "x",
        "tier": "active",
        "status": "active",
        "version": "1.0.0",
        "version_source": "package.json",
        "purpose": "does x",
        "updated": "2026-06-25",
    }
    fm.update(over)
    return fm


def test_valid_active_has_no_findings():
    assert validate_frontmatter(_active()) == []


def test_missing_required_active_field_is_fail():
    fm = _active()
    del fm["updated"]
    assert any(
        f.code == "missing_field" and "updated" in f.message and f.severity == "FAIL"
        for f in validate_frontmatter(fm)
    )


def test_parking_does_not_require_version():
    assert (
        validate_frontmatter({"name": "x", "tier": "parking", "status": "idea", "purpose": "x"})
        == []
    )


def test_bad_enum_is_fail():
    fm = {"name": "x", "tier": "parking", "status": "bogus", "purpose": "x"}
    assert any(f.code == "bad_enum" and f.severity == "FAIL" for f in validate_frontmatter(fm))


def test_foundation_not_bool_is_bad_type():
    assert any(
        f.code == "bad_type" and f.severity == "FAIL" and "foundation" in f.message
        for f in validate_frontmatter(_active(foundation="yes"))
    )


def test_applicable_standards_bad_item_is_contract_error():
    assert any(
        f.code == "contract_error" and f.severity == "FAIL" and "nope" in f.message
        for f in validate_frontmatter(_active(applicable_standards=["security", "nope"]))
    )


def test_applicable_standards_not_list_is_contract_error():
    assert any(
        f.code == "contract_error" and f.severity == "FAIL" and "applicable_standards" in f.message
        for f in validate_frontmatter(_active(applicable_standards="security"))
    )


def test_coolify_resources_not_list_of_str_is_bad_type():
    assert any(
        f.code == "bad_type" and f.severity == "FAIL" and "coolify_resources" in f.message
        for f in validate_frontmatter(_active(coolify_resources=[1, 2]))
    )


def test_foundation_true_with_valid_standards_has_no_new_findings():
    assert (
        validate_frontmatter(_active(foundation=True, applicable_standards=["project", "security"]))
        == []
    )


def test_foundation_true_without_applicable_standards_warns_incomplete():
    assert any(
        f.code == "foundation_incomplete" and f.severity == "WARN"
        for f in validate_frontmatter(_active(foundation=True))
    )


def test_foundation_true_infra_without_coolify_resources_warns_incomplete():
    assert any(
        f.code == "foundation_incomplete" and f.severity == "WARN"
        for f in validate_frontmatter(_active(foundation=True, applicable_standards=["infra"]))
    )


def test_no_census_keys_produces_no_census_findings():
    assert validate_frontmatter(_active()) == []


def test_map_form_applicable_standards_is_valid(base_fm):
    fm = {**base_fm, "applicable_standards": {"project": "1.0", "infra": None}}
    assert "bad_type" not in _codes(validate_frontmatter(fm))
    assert "contract_error" not in _codes(validate_frontmatter(fm))


def test_future_contract_marker_fails(base_fm):
    fm = {**base_fm, "foundation_contract": 2, "applicable_standards": {"project": "1.0"}}
    assert "contract_error" in _codes(validate_frontmatter(fm))


def test_malformed_exception_entry_fails(base_fm):
    fm = {
        **base_fm,
        "applicable_standards": {"project": "1.0"},
        "exceptions": [{"standard": "project"}],
    }
    assert "contract_error" in _codes(validate_frontmatter(fm))


def test_bad_required_checks_fails(base_fm):
    fm = {**base_fm, "applicable_standards": {"project": "1.0"}, "required_checks": "quality"}
    assert "contract_error" in _codes(validate_frontmatter(fm))


def test_factory_target_not_bool_is_bad_type():
    """A quoted "false" reads as "nothing declared" everywhere downstream, so
    without this FAIL a declaration could sit in the file and be inert in every
    consumer (ADR-0015)."""
    assert any(
        f.code == "bad_type" and f.severity == "FAIL" and "factory_target" in f.message
        for f in validate_frontmatter(_active(factory_target="false"))
    )


@pytest.mark.parametrize("declared", [True, False])
def test_a_bool_factory_target_is_accepted(declared):
    assert validate_frontmatter(_active(factory_target=declared)) == []
