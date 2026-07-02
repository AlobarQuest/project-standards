from pathlib import Path
from portfolio import config

def test_portfolio_home_defaults(monkeypatch):
    monkeypatch.delenv("PORTFOLIO_HOME", raising=False)
    assert config.portfolio_home() == Path.home() / ".portfolio"

def test_portfolio_home_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PORTFOLIO_HOME", str(tmp_path))
    assert config.portfolio_home() == tmp_path
    assert config.inbox_path() == tmp_path / "inbox.jsonl"

def test_security_standards_repo_default(monkeypatch):
    monkeypatch.delenv("SECURITY_STANDARDS_REPO", raising=False)
    assert config.security_standards_repo() == Path.home() / "Projects" / "security-standards"

def test_security_standards_repo_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SECURITY_STANDARDS_REPO", str(tmp_path))
    assert config.security_standards_repo() == tmp_path

def test_security_standards_src_default(monkeypatch):
    monkeypatch.delenv("SECURITY_STANDARDS_REPO", raising=False)
    assert config.security_standards_src() == config.security_standards_repo() / "src"

def test_code_standards_repo_default(monkeypatch):
    monkeypatch.delenv("CODE_STANDARDS_REPO", raising=False)
    assert config.code_standards_repo() == Path.home() / "Developer" / "code-standards"

def test_code_standards_repo_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CODE_STANDARDS_REPO", str(tmp_path))
    assert config.code_standards_repo() == tmp_path

def test_infra_report_dir_default(monkeypatch):
    monkeypatch.delenv("INFRADRIFT_REPORT_DIR", raising=False)
    assert config.infra_report_dir() == Path.home() / "infra-drift" / "reports"

def test_infra_report_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("INFRADRIFT_REPORT_DIR", str(tmp_path))
    assert config.infra_report_dir() == tmp_path

def test_exceptions_path_default(monkeypatch):
    monkeypatch.delenv("FOUNDATION_EXCEPTIONS", raising=False)
    p = config.exceptions_path()
    assert p.name == "foundation-exceptions.toml"
    repo_root = Path(config.__file__).resolve().parents[2]
    assert p == repo_root / "foundation-exceptions.toml"

def test_exceptions_path_override(monkeypatch, tmp_path):
    override = tmp_path / "custom-exceptions.toml"
    monkeypatch.setenv("FOUNDATION_EXCEPTIONS", str(override))
    assert config.exceptions_path() == override

def test_foundation_json_path_under_portfolio_home(portfolio_env):
    assert config.foundation_json_path() == portfolio_env / "foundation.json"

def test_foundation_digest_path_under_portfolio_home(portfolio_env):
    assert config.foundation_digest_path() == portfolio_env / "FOUNDATION.md"

def test_checker_timeout_default(monkeypatch):
    monkeypatch.delenv("FOUNDATION_TIMEOUT", raising=False)
    assert config.checker_timeout() == 120

def test_checker_timeout_override(monkeypatch):
    monkeypatch.setenv("FOUNDATION_TIMEOUT", "45")
    assert config.checker_timeout() == 45

def test_checker_timeout_non_numeric_falls_back(monkeypatch):
    monkeypatch.setenv("FOUNDATION_TIMEOUT", "abc")
    assert config.checker_timeout() == 120

def test_infra_max_age_hours_default(monkeypatch):
    monkeypatch.delenv("INFRA_MAX_AGE_HOURS", raising=False)
    assert config.infra_max_age_hours() == 36

def test_infra_max_age_hours_override(monkeypatch):
    monkeypatch.setenv("INFRA_MAX_AGE_HOURS", "12")
    assert config.infra_max_age_hours() == 12

def test_infra_max_age_hours_non_numeric_falls_back(monkeypatch):
    monkeypatch.setenv("INFRA_MAX_AGE_HOURS", "abc")
    assert config.infra_max_age_hours() == 36
