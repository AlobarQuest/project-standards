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


@pytest.mark.parametrize("key", ["factory_target", "factory_target_reason"])
def test_a_leftover_factory_target_key_warns_that_it_moved(key):
    """The declaration moved to `factory-target.toml` on 2026-09-11. Nothing
    reads these keys any more, so one left behind is decoration that reads like
    configuration -- somebody edits it and the estate does not change."""
    findings = validate_frontmatter(_active(**{key: False if key == "factory_target" else "why"}))
    assert [(f.severity, f.code) for f in findings] == [("WARN", "factory_target_moved")]
    assert key in findings[0].message


def test_the_moved_key_warns_rather_than_fails():
    """WARN, not FAIL, and the reason is mechanical: `project.manifest` is an
    ADMISSION check whose status comes from `lint`'s FAILs, so a FAIL here
    would fail admission for any checkout that had not yet pulled the removal.
    A rot-guard that takes repositories out of admission is worse than the rot."""
    findings = validate_frontmatter(_active(factory_target=True))
    assert findings and all(f.severity == "WARN" for f in findings)
