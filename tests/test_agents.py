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


# ---------------------------------------------------------------------------
# PortfolioManagerAgent conviction normalisation (A2)
# ---------------------------------------------------------------------------

def _pm_with_weights():
    from app.agents.portfolio_manager import PortfolioManagerAgent
    from app.llm.gateway import LLMGateway

    gw = MagicMock(spec=LLMGateway)
    gw.complete.side_effect = Exception("force fallback")
    weights = {
        "technical": 0.30, "forecast": 0.20, "sentiment": 0.20, "onchain": 0.15, "news": 0.15
    }
    return PortfolioManagerAgent(gw, weights)


def _view(agent: str, signal: str, confidence: float) -> AgentView:
    return AgentView(
        agent=agent, asset="BTC/USDT", signal=signal, confidence=confidence, rationale="test"
    )


def test_aggregate_missing_technical_forecast():
    pm = _pm_with_weights()
    views = [
        _view("technical", "neutral", 0.0),
        _view("forecast", "neutral", 0.0),
        _view("sentiment", "long", 0.9),
        _view("onchain", "neutral", 0.0),
        _view("news", "neutral", 0.0),
    ]
    idea = pm.aggregate(views, "BTC/USDT", _ctx())
    # active_weight = 0.20 (sentiment only); norm_score = 0.9*0.20/0.20 = 0.90
    # old behaviour: 0.9*0.20 / 1.0 = 0.18 → conviction 0.18
    # new behaviour: conviction should be materially higher (bounded by low_coverage cap at 0.30)
    assert idea.conviction >= 0.25  # meaningfully above the old 0.18


def test_aggregate_single_agent_capped():
    pm = _pm_with_weights()
    views = [_view("news", "long", 0.95)]
    idea = pm.aggregate(views, "BTC/USDT", _ctx())
    # active_weight = 0.15 < 0.30 → low_coverage → norm_score capped at 0.30
    assert idea.conviction <= 0.30
    assert "low coverage" in idea.combined_rationale


def test_aggregate_all_agents_active():
    pm = _pm_with_weights()
    views = [
        _view("technical", "long", 0.8),
        _view("forecast", "long", 0.7),
        _view("sentiment", "long", 0.6),
        _view("onchain", "long", 0.5),
        _view("news", "long", 0.4),
    ]
    idea = pm.aggregate(views, "BTC/USDT", _ctx())
    # All active → norm by total weight; no low_coverage cap; score should be >0
    assert idea.conviction > 0
    assert "low coverage" not in idea.combined_rationale


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
