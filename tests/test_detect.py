from portfolio.detect import detect_name, detect_purpose, detect_version, is_git


def test_version_from_package_json(make_repo):
    assert detect_version(make_repo("p", files={"package.json": '{"version": "3.4.5"}'})) == (
        "3.4.5",
        "package.json",
    )


def test_version_from_pyproject(make_repo):
    assert detect_version(
        make_repo("p", files={"pyproject.toml": '[project]\nversion = "2.0.1"\n'})
    ) == ("2.0.1", "pyproject")


def test_version_none_when_undetectable(make_repo):
    assert detect_version(make_repo("p", files={"README.md": "hi"})) == ("n/a", "none")


def test_version_survives_malformed_package_json(make_repo):
    assert detect_version(make_repo("p", files={"package.json": "{not json"})) == ("n/a", "none")


def test_name_is_dir_name(make_repo):
    assert detect_name(make_repo("contacts")) == "contacts"


def test_is_git_true_false(make_repo):
    assert is_git(make_repo("g", git=True)) is True
    assert is_git(make_repo("ng", git=False)) is False


def test_purpose_from_readme_first_prose_line(make_repo):
    assert (
        detect_purpose(make_repo("p", files={"README.md": "# Title\n\nDoes the thing well.\n"}))
        == "Does the thing well."
    )


def test_version_survives_non_dict_json(make_repo):
    assert detect_version(make_repo("p", files={"package.json": "[]"})) == ("n/a", "none")
