from portfolio.manifest import (
    append_backlog_item,
    parse_backlog,
    parse_frontmatter,
    read_manifest,
    write_manifest,
)

MANIFEST = """---
name: demo
tier: active
status: active
version: 1.2.0
version_source: package.json
purpose: demo thing
updated: 2026-06-01
---

## Backlog
- [ ] (P2) existing item — added 2026-05-01

## Future plans
later
"""


def test_round_trip_preserves_fields(tmp_path):
    (tmp_path / "PROJECT.md").write_text(MANIFEST)
    m = read_manifest(tmp_path)
    assert m.frontmatter["name"] == "demo" and "Future plans" in m.body
    write_manifest(m)
    assert read_manifest(tmp_path).frontmatter["version"] == "1.2.0"


def test_parse_backlog_extracts_priority_and_date(tmp_path):
    (tmp_path / "PROJECT.md").write_text(MANIFEST)
    items = parse_backlog(read_manifest(tmp_path).body)
    assert (
        items[0].priority == "P2" and items[0].added == "2026-05-01" and items[0].malformed is False
    )


def test_parse_backlog_accepts_dash_variants():
    # en-dash, ASCII hyphen, double-hyphen all parse, not just em-dash  [debate-fix]
    body = (
        "## Backlog\n"
        "- [ ] (P1) en dash – added 2026-01-01\n"
        "- [ ] (P2) ascii hyphen - added 2026-02-02\n"
        "- [ ] (P3) double -- added 2026-03-03\n"
    )
    items = parse_backlog(body)
    assert [i.added for i in items] == ["2026-01-01", "2026-02-02", "2026-03-03"]
    assert all(not i.malformed for i in items)


def test_completed_items_parse_not_malformed():
    items = parse_backlog("## Backlog\n- [x] (P2) done thing — added 2026-01-01\n")
    assert items[0].malformed is False and items[0].text == "done thing"


def test_append_is_additive_and_preserves_lines(tmp_path):
    (tmp_path / "PROJECT.md").write_text(MANIFEST)
    append_backlog_item(tmp_path, "new thing", "P1", "2026-06-25")
    body = (tmp_path / "PROJECT.md").read_text()
    assert "existing item" in body and "## Future plans" in body
    assert "(P1) new thing — added 2026-06-25" in body


def test_append_when_no_backlog_section(tmp_path):
    (tmp_path / "PROJECT.md").write_text(
        "---\nname: x\ntier: parking\nstatus: idea\npurpose: p\n---\n\nbody\n"
    )
    append_backlog_item(tmp_path, "first", None, "2026-06-25")
    assert "## Backlog" in (tmp_path / "PROJECT.md").read_text()
    assert "first — added 2026-06-25" in (tmp_path / "PROJECT.md").read_text()


def test_parse_frontmatter_bad_yaml_does_not_raise():
    fm, _ = parse_frontmatter("---\nname: x\n  bad: : :\n---\nbody\n")
    assert "_yaml_error" in fm


def test_read_missing_returns_none(tmp_path):
    assert read_manifest(tmp_path) is None
