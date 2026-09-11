import pytest

from portfolio.factory_target import FactoryTargetError, factory_target_declaration

DECLARATION = (
    "# Whether the SDS factory may be dispatched work in this repository.\n"
    "# Absence of this file means NO -- participation is declared, never assumed.\n"
    "factory_target = {value}\n"
    'factory_target_reason = "{reason}"\n'
)


def _repo(tmp_path, body=None):
    repo = tmp_path / "repo"
    repo.mkdir(exist_ok=True)
    if body is not None:
        (repo / "factory-target.toml").write_text(body)
    return repo


def test_a_declaration_reads_its_bool_and_its_reason(tmp_path):
    repo = _repo(tmp_path, DECLARATION.format(value="true", reason="onboarded 2026-09-11"))
    assert factory_target_declaration(repo) == (True, "onboarded 2026-09-11")


def test_a_declared_non_target_reads_false_and_its_reason(tmp_path):
    repo = _repo(tmp_path, DECLARATION.format(value="false", reason="the runner may not self-host"))
    assert factory_target_declaration(repo) == (False, "the runner may not self-host")


def test_no_file_at_all_is_not_a_target(tmp_path):
    """ADR-0015 as Devon restated it on 2026-09-11: participation is DECLARED,
    never assumed, so a repository that has said nothing has not opted in.

    This inverts the frontmatter era, where an absent key meant "nothing
    declared" and left every consumer where it was. Silence is now an answer,
    and `(False, None)` is how the reader says "not a target, and it did not
    tell me why" -- which its consumers word differently from an explicit
    `false`, because the two have different fixes."""
    assert factory_target_declaration(_repo(tmp_path)) == (False, None)


@pytest.mark.parametrize(
    "body",
    [
        'factory_target = "true"\nfactory_target_reason = "r"\n',
        'factory_target = 1\nfactory_target_reason = "r"\n',
        'factory_target_reason = "r"\n',
    ],
)
def test_anything_short_of_a_bool_raises_rather_than_guessing(tmp_path, body):
    """A file that exists and does not say `true` or `false` is neither an
    opt-in nor the deliberate silence of absence. Reading it as False would
    hand a repository the non-target's exemption on a typo; reading it as True
    would demand a caller nobody asked for. Both consumers turn the raised
    error into their own fail-closed answer."""
    with pytest.raises(FactoryTargetError, match="factory_target"):
        factory_target_declaration(_repo(tmp_path, body))


@pytest.mark.parametrize(
    "body",
    [
        "factory_target = true\n",
        'factory_target = true\nfactory_target_reason = ""\n',
        'factory_target = false\nfactory_target_reason = "   "\n',
        "factory_target = false\nfactory_target_reason = 7\n",
    ],
)
def test_the_reason_is_required_on_both_answers(tmp_path, body):
    """Requiring both keys includes the reason on a `true`: a bare `true` becomes
    folklore, and six months later nobody can say whether it was a decision or
    a default somebody copied. Required on `false` for the same reason, which
    is the case the frontmatter era let through (`factory_target: false` with
    no reason read as a declaration with no words)."""
    with pytest.raises(FactoryTargetError, match="factory_target_reason"):
        factory_target_declaration(_repo(tmp_path, body))


def test_a_file_that_is_not_toml_raises(tmp_path):
    with pytest.raises(FactoryTargetError, match="cannot be read"):
        factory_target_declaration(_repo(tmp_path, "factory_target: true\n"))


def test_a_directory_in_the_files_place_is_not_a_declaration(tmp_path):
    """`is_file()` rather than `exists()`: a directory of that name is not a
    file the reader can open, and raising OSError out of a helper whose whole
    job is to answer a question would surface as an unhandled crash."""
    repo = _repo(tmp_path)
    (repo / "factory-target.toml").mkdir()
    assert factory_target_declaration(repo) == (False, None)
