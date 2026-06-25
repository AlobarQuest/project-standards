from portfolio.schema import validate_frontmatter

def _active(**over):
    fm = {"name": "x", "tier": "active", "status": "active", "version": "1.0.0",
          "version_source": "package.json", "purpose": "does x", "updated": "2026-06-25"}
    fm.update(over); return fm

def test_valid_active_has_no_findings():
    assert validate_frontmatter(_active()) == []

def test_missing_required_active_field_is_fail():
    fm = _active(); del fm["updated"]
    assert any(f.code == "missing_field" and "updated" in f.message and f.severity == "FAIL"
               for f in validate_frontmatter(fm))

def test_parking_does_not_require_version():
    assert validate_frontmatter({"name": "x", "tier": "parking", "status": "idea", "purpose": "x"}) == []

def test_bad_enum_is_fail():
    assert any(f.code == "bad_enum" and f.severity == "FAIL"
               for f in validate_frontmatter({"name": "x", "tier": "parking", "status": "bogus", "purpose": "x"}))
