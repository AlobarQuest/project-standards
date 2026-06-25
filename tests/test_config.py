from pathlib import Path
from portfolio import config

def test_portfolio_home_defaults(monkeypatch):
    monkeypatch.delenv("PORTFOLIO_HOME", raising=False)
    assert config.portfolio_home() == Path.home() / ".portfolio"

def test_portfolio_home_override(monkeypatch, tmp_path):
    monkeypatch.setenv("PORTFOLIO_HOME", str(tmp_path))
    assert config.portfolio_home() == tmp_path
    assert config.inbox_path() == tmp_path / "inbox.jsonl"
