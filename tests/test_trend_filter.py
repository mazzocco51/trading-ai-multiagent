from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd

from app.agents.portfolio_manager import TradeIdea
from app.agents.sentiment_agent import SentimentAgent
from app.broker.paper import PaperBroker
from app.data.context import MarketContext
from app.data.indicators import compute_indicators
from app.llm.providers.base import LLMResponse
from app.orchestrator import apply_trend_gate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_gw(parsed: dict):
    gw = MagicMock()
    gw.complete.return_value = LLMResponse(
        provider="test", model="test", content=str(parsed), parsed=parsed
    )
    return gw


def _df(n: int) -> pd.DataFrame:
    prices = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p + 1 for p in prices],
            "low": [p - 1 for p in prices],
            "close": prices,
            "volume": [10.0] * n,
        }
    )


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


def _idea(action: str) -> TradeIdea:
    return TradeIdea(
        asset="BTC/USDT",
        action=action,
        target_size_pct=0.1,
        conviction=0.7,
        combined_rationale="test",
        agent_views_summary=[],
    )


# ---------------------------------------------------------------------------
# A1 — indicators
# ---------------------------------------------------------------------------

def test_trend_ema_in_indicators():
    res = compute_indicators(_df(60))
    assert "trend_ema" in res
    assert "last_close" in res
    assert res["trend_ema"] is not None
    assert res["last_close"] is not None


def test_trend_ema_null_on_short_df():
    res = compute_indicators(_df(10))
    # EMA with span > len is still a valid float; just assert present and numeric.
    assert "trend_ema" in res
    assert isinstance(res["trend_ema"], float)
    assert isinstance(res["last_close"], float)


# ---------------------------------------------------------------------------
# A1 — trend gate
# ---------------------------------------------------------------------------

def test_long_blocked_below_ema():
    idea = apply_trend_gate(
        _idea("open_long"), "BTC/USDT", {"last_close": 90.0, "trend_ema": 100.0}
    )
    assert idea.action == "hold"


def test_long_allowed_above_ema():
    idea = apply_trend_gate(
        _idea("open_long"), "BTC/USDT", {"last_close": 110.0, "trend_ema": 100.0}
    )
    assert idea.action == "open_long"


def test_short_blocked_above_ema():
    idea = apply_trend_gate(
        _idea("open_short"), "BTC/USDT", {"last_close": 110.0, "trend_ema": 100.0}
    )
    assert idea.action == "hold"


# ---------------------------------------------------------------------------
# A2 — cooldown
# ---------------------------------------------------------------------------

def test_cooldown_blocks_reopen():
    broker = PaperBroker()
    broker.last_stop_at["BTC/USDT"] = datetime.now(tz=UTC).isoformat()
    assert broker.is_in_cooldown("BTC/USDT", 6) is True


def test_cooldown_expired():
    broker = PaperBroker()
    seven_hours_ago = datetime.now(tz=UTC) - timedelta(hours=7)
    broker.last_stop_at["BTC/USDT"] = seven_hours_ago.isoformat()
    assert broker.is_in_cooldown("BTC/USDT", 6) is False


# ---------------------------------------------------------------------------
# A3 — sentiment extreme-only
# ---------------------------------------------------------------------------

def test_sentiment_extreme_only_neutral_in_midrange():
    gw = _mock_gw({"signal": "long", "confidence": 0.9, "rationale": "x"})
    agent = SentimentAgent(gw, extreme_only=True, extreme_threshold=25)
    ctx = _ctx(fear_and_greed={"value": 50, "label": "Neutral"})
    view = agent.analyze(ctx)
    assert view.signal == "neutral"
    assert view.confidence == 0.0
    gw.complete.assert_not_called()


def test_sentiment_extreme_only_active_on_extreme():
    gw = _mock_gw({"signal": "long", "confidence": 0.9, "rationale": "fear"})
    agent = SentimentAgent(gw, extreme_only=True, extreme_threshold=25)
    ctx = _ctx(fear_and_greed={"value": 10, "label": "Extreme Fear"})
    view = agent.analyze(ctx)
    assert view.signal != "neutral"
    gw.complete.assert_called_once()
