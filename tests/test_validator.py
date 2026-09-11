from datetime import date

from portfolio.validator import lint


def _good_active():
    return (
        "---\nname: x\ntier: active\nstatus: active\nversion: 1.0.0\n"
        "version_source: package.json\npurpose: p\nupdated: 2026-06-25\n---\n\n## Backlog\n"
    )


def test_missing_manifest_is_fail(make_repo):
    assert any(f.code == "missing_manifest" and f.severity == "FAIL" for f in lint(make_repo("x")))


def test_conforming_active_repo_is_clean(make_repo):
    repo = make_repo(
        "x", files={"PROJECT.md": _good_active(), "package.json": '{"version":"1.0.0"}'}
    )
    assert lint(repo, today=date(2026, 6, 26)) == []


def test_bad_yaml_is_fail(make_repo):
    repo = make_repo("x", files={"PROJECT.md": "---\nname: x\n bad: : :\n---\n"})
    assert any(
        f.code == "bad_yaml" and f.severity == "FAIL" for f in lint(repo, today=date(2026, 6, 26))
    )


def test_non_git_active_is_fail(make_repo):
    repo = make_repo(
        "x",
        git=False,
        files={
            "PROJECT.md": _good_active().replace("1.0.0", "n/a").replace("package.json", "none")
        },
    )
    assert any(
        f.code == "not_git" and f.severity == "FAIL" for f in lint(repo, today=date(2026, 6, 26))
    )


def test_aged_backlog_item_is_warn(make_repo):
    body = _good_active().replace("## Backlog\n", "## Backlog\n- [ ] (P3) old — added 2025-01-01\n")
    repo = make_repo("x", files={"PROJECT.md": body})
    assert any(
        f.code == "aged_item" and f.severity == "WARN" for f in lint(repo, today=date(2026, 6, 26))
    )


def test_a_malformed_declaration_file_is_a_fail(make_repo):
    """`runner.caller` reports a broken `factory-target.toml` as `unknown`, but
    only to someone already running the kit against that repository. This is
    the loud one: `lint` runs in the nightly portfolio scan, so a declaration
    that does not parse surfaces without anyone going looking for it."""
    repo = make_repo(
        "x",
        files={
            "PROJECT.md": _good_active(),
            "package.json": '{"version":"1.0.0"}',
            "factory-target.toml": 'factory_target = "true"\n',
        },
    )
    findings = lint(repo, today=date(2026, 6, 26))
    assert [(f.severity, f.code) for f in findings] == [("FAIL", "factory_target_invalid")]


def test_a_well_formed_declaration_is_clean(make_repo):
    repo = make_repo(
        "x",
        files={
            "PROJECT.md": _good_active(),
            "package.json": '{"version":"1.0.0"}',
            "factory-target.toml": 'factory_target = true\nfactory_target_reason = "a target"\n',
        },
    )
    assert lint(repo, today=date(2026, 6, 26)) == []


def test_no_declaration_file_is_clean(make_repo):
    """Absence means not a target, which is an answer rather than a defect --
    `lint` must not report the estate's every non-target repository."""
    repo = make_repo(
        "x", files={"PROJECT.md": _good_active(), "package.json": '{"version":"1.0.0"}'}
    )
    assert lint(repo, today=date(2026, 6, 26)) == []
