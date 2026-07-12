from __future__ import annotations

from app.config import Settings


def test_default_assets():
    s = Settings()
    assert "BTC/USDT" in s.assets
    assert len(s.assets) == 3


def test_default_broker_is_paper():
    s = Settings()
    assert s.broker == "paper"


def test_default_timeframe():
    s = Settings()
    assert s.timeframe == "1h"


def test_risk_limits_sane():
    s = Settings()
    assert 0 < s.default_sl_pct < s.default_tp_pct
    assert s.max_position_pct <= 1.0
    assert s.max_total_exposure_pct <= 1.0


def test_agent_weights_sum_to_one():
    s = Settings()
    total = sum(s.agent_weights.values())
    assert abs(total - 1.0) < 1e-9


def test_llm_provider_order():
    s = Settings()
    assert s.llm_provider_order[0] == "groq"
    assert set(s.llm_provider_order) == {"groq", "gemini", "openrouter"}


def test_override_via_env(monkeypatch):
    monkeypatch.setenv("TIMEFRAME", "15m")
    monkeypatch.setenv("BROKER", "paper")
    s = Settings()
    assert s.timeframe == "15m"
