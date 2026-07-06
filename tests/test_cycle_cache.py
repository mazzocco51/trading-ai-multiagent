"""Intra-cycle AgentView cache + rate-limit UX degradation tests."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from sqlalchemy.orm import sessionmaker

from app.agents.base import degraded_rationale
from app.agents.news_agent import NewsAgent
from app.agents.sentiment_agent import SentimentAgent
from app.broker.paper import PaperBroker
from app.config import Settings
from app.data.context import MarketContext
from app.llm.gateway import LLMRateLimited
from app.llm.providers.base import LLMResponse
from app.orchestrator import run_cycle
from app.persistence.models import init_db

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(asset: str, fng: dict | None = None, headlines: list | None = None) -> MarketContext:
    return MarketContext(
        asset=asset,
        timeframe="1h",
        fear_and_greed=fng or {},
        news_headlines=headlines or [],
    )


def _payload_gateway() -> MagicMock:
    payload = {
        "action": "hold",
        "target_size_pct": 0.0,
        "conviction": 0.1,
        "combined_rationale": "neutral",
        "signal": "neutral",
        "confidence": 0.5,
        "rationale": "no clear signal",
        "regime": "neutral",
        "contrarian": False,
        "headline_risk": "low",
        "summary": "quiet",
        "key_levels": {},
        "bull": "up",
        "bear": "down",
    }
    gw = MagicMock()
    gw.complete.return_value = LLMResponse(
        provider="test", model="test", content=json.dumps(payload), parsed=payload
    )
    return gw


# ---------------------------------------------------------------------------
# cache_key semantics
# ---------------------------------------------------------------------------


def test_sentiment_cache_key_asset_independent():
    agent = SentimentAgent(MagicMock())
    fng = {"value": 10, "label": "Extreme Fear"}
    k_btc = agent.cache_key(_ctx("BTC/USDT", fng=fng))
    k_eth = agent.cache_key(_ctx("ETH/USDT", fng=fng))
    assert k_btc == k_eth is not None


def test_sentiment_cache_key_changes_with_fng():
    agent = SentimentAgent(MagicMock())
    k1 = agent.cache_key(_ctx("BTC/USDT", fng={"value": 10, "label": "Extreme Fear"}))
    k2 = agent.cache_key(_ctx("BTC/USDT", fng={"value": 80, "label": "Greed"}))
    assert k1 != k2


def test_news_cache_key_same_headlines_shared():
    agent = NewsAgent(MagicMock())
    heads = ["ETF inflows rise", "Exchange outage resolved"]
    assert agent.cache_key(_ctx("BTC/USDT", headlines=heads)) == agent.cache_key(
        _ctx("SOL/USDT", headlines=heads)
    )
    assert agent.cache_key(_ctx("BTC/USDT", headlines=heads)) != agent.cache_key(
        _ctx("BTC/USDT", headlines=["different"])
    )


# ---------------------------------------------------------------------------
# (c) intra-cycle cache avoids duplicate LLM calls across assets
# ---------------------------------------------------------------------------


def test_run_cycle_reuses_global_views_across_assets():
    engine = init_db("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    settings = Settings(assets=["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    broker = PaperBroker(10_000)
    gateway = _payload_gateway()

    fng = {"value": 10, "label": "Extreme Fear"}  # extreme → sentiment calls the LLM
    heads = ["shared headline A", "shared headline B"]

    def fake_ctx(asset, timeframe, *args, **kwargs):
        return _ctx(asset, fng=fng, headlines=heads)

    with patch("app.orchestrator.build_context", side_effect=fake_ctx):
        results = run_cycle(settings, broker, gateway, session)

    assert len(results) == 3

    calls = [c.args + tuple(c.kwargs.values()) for c in gateway.complete.call_args_list]
    user_msgs = [" ".join(str(a) for a in call) for call in calls]
    sentiment_calls = [m for m in user_msgs if "fear_and_greed_value" in m]
    news_calls = [m for m in user_msgs if '"headlines"' in m]
    # Global signals: ONE LLM call each, reused for the other two assets
    assert len(sentiment_calls) == 1
    assert len(news_calls) == 1


def test_run_cycle_cached_view_carries_current_asset():
    engine = init_db("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    settings = Settings(assets=["BTC/USDT", "ETH/USDT"])
    broker = PaperBroker(10_000)
    gateway = _payload_gateway()

    from app.agents.portfolio_manager import PortfolioManagerAgent

    captured: list = []
    real_aggregate = PortfolioManagerAgent.aggregate

    def spy_aggregate(self, views, asset, ctx, **kwargs):
        captured.append((asset, [v.asset for v in views]))
        return real_aggregate(self, views, asset, ctx, **kwargs)

    fng = {"value": 10, "label": "Extreme Fear"}

    with (
        patch("app.orchestrator.build_context", side_effect=lambda a, *args, **k: _ctx(a, fng=fng)),
        patch.object(PortfolioManagerAgent, "aggregate", spy_aggregate),
    ):
        run_cycle(settings, broker, gateway, session)

    # Every view handed to the PM must carry the asset of the current loop
    # iteration, even when it came from the cache.
    for asset, view_assets in captured:
        assert all(va == asset for va in view_assets)


# ---------------------------------------------------------------------------
# (UX) rate-limited degradation message
# ---------------------------------------------------------------------------


def test_degraded_rationale_rate_limited_is_friendly():
    msg = degraded_rationale(LLMRateLimited("All providers rate-limited (429)"))
    assert msg == "temporaneamente non disponibile (rate-limited)"
    assert "429" not in msg
    assert "http" not in msg.lower()


def test_degraded_rationale_generic_error_kept():
    assert "boom" in degraded_rationale(RuntimeError("boom"))


def test_sentiment_agent_rate_limited_rationale():
    gw = MagicMock()
    gw.complete.side_effect = LLMRateLimited("All providers rate-limited (429)")
    agent = SentimentAgent(gw, extreme_only=False)
    view = agent.analyze(_ctx("BTC/USDT", fng={"value": 50, "label": "Neutral"}))
    assert view.signal == "neutral"
    assert view.confidence == 0.0
    assert view.rationale == "temporaneamente non disponibile (rate-limited)"


def test_news_agent_rate_limited_rationale():
    gw = MagicMock()
    gw.complete.side_effect = LLMRateLimited("All providers rate-limited (429)")
    agent = NewsAgent(gw)
    view = agent.analyze(_ctx("BTC/USDT", headlines=["headline"]))
    assert view.rationale == "temporaneamente non disponibile (rate-limited)"
