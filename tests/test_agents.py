from __future__ import annotations

from unittest.mock import MagicMock

from app.agents.base import AgentView
from app.agents.forecast_agent import ForecastAgent
from app.agents.news_agent import NewsAgent
from app.agents.onchain import OnChainAgent
from app.agents.sentiment_agent import SentimentAgent
from app.agents.technical import TechnicalAgent
from app.data.context import MarketContext
from app.llm.providers.base import LLMResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_gw(parsed: dict):
    gw = MagicMock()
    gw.complete.return_value = LLMResponse(
        provider="test", model="test",
        content=str(parsed), parsed=parsed
    )
    return gw


def _ctx(**kwargs) -> MarketContext:
    defaults = dict(
        asset="BTC/USDT",
        timeframe="1h",
        ohlcv=[],
        indicators={},
        forecast={},
        fear_and_greed={},
        whale_events=[],
        news_headlines=[],
        degraded_sources=[],
    )
    defaults.update(kwargs)
    return MarketContext(**defaults)


# ---------------------------------------------------------------------------
# TechnicalAgent
# ---------------------------------------------------------------------------

def test_technical_agent_long():
    indicators = {"rsi": 25, "macd": 100, "pivot": 50000}
    ctx = _ctx(indicators=indicators)
    parsed = {"signal": "long", "confidence": 0.8, "rationale": "oversold", "key_levels": {}}
    agent = TechnicalAgent(gateway=_mock_gw(parsed))
    view = agent.analyze(ctx)
    assert isinstance(view, AgentView)
    assert view.signal == "long"
    assert view.confidence == 0.8


def test_technical_agent_gateway_failure():
    ctx = _ctx(indicators={"rsi": 50})
    gw = MagicMock()
    gw.complete.side_effect = Exception("network error")
    agent = TechnicalAgent(gateway=gw)
    view = agent.analyze(ctx)
    assert view.signal == "neutral"
    assert view.confidence == 0.0


# ---------------------------------------------------------------------------
# ForecastAgent
# ---------------------------------------------------------------------------

def test_forecast_agent_degraded():
    ctx = _ctx(forecast={"degraded": True})
    gw = MagicMock()
    agent = ForecastAgent(gateway=gw)
    view = agent.analyze(ctx)
    assert view.signal == "neutral"
    gw.complete.assert_not_called()


def test_forecast_agent_short():
    forecast = {
        "expected_move_pct": -0.03,
        "direction": "down",
        "confidence": 0.7,
        "mae": 100,
        "degraded": False,
    }
    ctx = _ctx(forecast=forecast)
    parsed = {
        "signal": "short",
        "confidence": 0.65,
        "rationale": "down trend",
        "expected_move_pct": -0.03,
        "uncertainty": "medium",
    }
    agent = ForecastAgent(gateway=_mock_gw(parsed))
    view = agent.analyze(ctx)
    assert view.signal == "short"


# ---------------------------------------------------------------------------
# SentimentAgent
# ---------------------------------------------------------------------------

def test_sentiment_agent_extreme_fear():
    fng = {"value": 12, "label": "Extreme Fear"}
    ctx = _ctx(fear_and_greed=fng)
    parsed = {
        "signal": "long",
        "confidence": 0.7,
        "rationale": "contrarian",
        "regime": "extreme_fear",
        "contrarian": True,
    }
    agent = SentimentAgent(gateway=_mock_gw(parsed))
    view = agent.analyze(ctx)
    assert view.signal == "long"


# ---------------------------------------------------------------------------
# OnChainAgent
# ---------------------------------------------------------------------------

def test_onchain_agent_no_events():
    ctx = _ctx(whale_events=[])
    gw = MagicMock()
    agent = OnChainAgent(gateway=gw)
    view = agent.analyze(ctx)
    assert view.signal == "neutral"
    gw.complete.assert_not_called()


# ---------------------------------------------------------------------------
# NewsAgent
# ---------------------------------------------------------------------------

def test_news_agent_no_headlines():
    ctx = _ctx(news_headlines=[])
    gw = MagicMock()
    agent = NewsAgent(gateway=gw)
    view = agent.analyze(ctx)
    assert view.signal == "neutral"
    gw.complete.assert_not_called()


def test_news_agent_high_risk():
    headlines = [{"title": "Exchange hacked", "published_at": "2026-06-21"}]
    ctx = _ctx(news_headlines=headlines)
    parsed = {
        "signal": "short",
        "confidence": 0.8,
        "rationale": "hack",
        "headline_risk": "high",
        "summary": "hack",
    }
    agent = NewsAgent(gateway=_mock_gw(parsed))
    view = agent.analyze(ctx)
    assert view.signal == "short"
