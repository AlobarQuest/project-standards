import pytest

from portfolio.sds_decisions import (
    DECISIONS_FILE,
    Decisions,
    DecisionsError,
    check_decisions,
    onboarding_dir,
    read_decisions,
)


def _write(name, body):
    directory = onboarding_dir(name)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / DECISIONS_FILE).write_text(body)


def _ids(out):
    return [d["id"] for d in out["details"]]


def test_onboarding_dir_lives_under_portfolio_home(portfolio_env):
    assert onboarding_dir("r") == portfolio_env / "onboarding" / "r"


def test_absent_file_reads_as_all_none(portfolio_env):
    assert read_decisions("r") == Decisions(None, None, None)


def test_absent_file_is_a_violation_listing_both_decisions(portfolio_env):
    out = check_decisions("r")
    assert out["id"] == "sds.decisions"
    assert out["status"] == "violation"
    assert set(_ids(out)) == {"sds.decide-onboard", "sds.decide-landing"}


def test_message_and_fix_name_the_file_and_show_the_format(portfolio_env):
    out = check_decisions("r")
    path = str(onboarding_dir("r") / DECISIONS_FILE)
    assert path in out["fix"]
    assert "onboard_reason" in out["fix"]
    assert 'landing = "inert"' in out["fix"]
    assert all(path in d["message"] for d in out["details"])


def test_malformed_file_is_a_violation_naming_the_error(portfolio_env):
    _write("r", "onboard = ")
    out = check_decisions("r")
    assert out["status"] == "violation"
    assert _ids(out) == ["sds.decisions-unreadable"]
    assert str(onboarding_dir("r") / DECISIONS_FILE) in out["details"][0]["message"]


@pytest.mark.parametrize(
    "body",
    [
        'onboard = "yes"\n',
        "onboard = true\nonboard_reason = 3\n",
        'onboard = true\nonboard_reason = "x"\nlanding = true\n',
        'onboard = true\nonboard_reason = "x"\nlanding = "maybe"\n',
    ],
)
def test_wrong_type_or_value_is_unreadable(portfolio_env, body):
    _write("r", body)
    with pytest.raises(DecisionsError):
        read_decisions("r")
    assert _ids(check_decisions("r")) == ["sds.decisions-unreadable"]


def test_declined_onboarding_is_a_refusal(portfolio_env):
    _write("r", "onboard = false\n")
    out = check_decisions("r")
    assert out["status"] == "violation"
    assert _ids(out) == ["sds.refused-not-onboarding"]


def test_declined_onboarding_hides_landing_problems(portfolio_env):
    _write("r", 'onboard = false\nlanding = "redeploys"\n')
    assert _ids(check_decisions("r")) == ["sds.refused-not-onboarding"]


def test_redeploys_is_a_refusal(portfolio_env):
    _write("r", 'onboard = true\nonboard_reason = "why"\nlanding = "redeploys"\n')
    out = check_decisions("r")
    assert out["status"] == "violation"
    assert _ids(out) == ["sds.refused-redeploys"]


def test_partial_file_reports_only_the_missing_decision(portfolio_env):
    _write("r", 'onboard = true\nonboard_reason = "why"\n')
    assert _ids(check_decisions("r")) == ["sds.decide-landing"]


def test_landing_only_reports_the_onboard_decision(portfolio_env):
    _write("r", 'landing = "inert"\n')
    assert _ids(check_decisions("r")) == ["sds.decide-onboard"]


@pytest.mark.parametrize("reason", ['onboard_reason = ""\n', 'onboard_reason = "  "\n', ""])
def test_onboard_true_requires_a_reason(portfolio_env, reason):
    _write("r", f'onboard = true\n{reason}landing = "inert"\n')
    out = check_decisions("r")
    assert out["status"] == "violation"
    assert _ids(out) == ["sds.decide-onboard"]
    assert "onboard_reason" in out["details"][0]["message"]


def test_complete_inert_decision_passes(portfolio_env):
    _write("r", 'onboard = true\nonboard_reason = "why"\nlanding = "inert"\n')
    out = check_decisions("r")
    assert out["status"] == "pass"
    assert out["details"] == []
    assert read_decisions("r") == Decisions(True, "why", "inert")
