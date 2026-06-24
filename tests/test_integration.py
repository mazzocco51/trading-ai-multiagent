"""Integration tests for RiskManager, PortfolioManagerAgent, and the orchestrator."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import sessionmaker

from app.agents.base import AgentView
from app.agents.portfolio_manager import PortfolioManagerAgent, TradeIdea
from app.agents.risk_manager import RiskManager
from app.broker.paper import PaperBroker
from app.config import Settings
from app.data.context import MarketContext
from app.llm.providers.base import LLMResponse
from app.orchestrator import run_cycle
from app.persistence.models import Decision, init_db

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _settings(**overrides) -> Settings:
    """Return a Settings instance with sensible test defaults."""
    defaults: dict = {}
    defaults.update(overrides)
    return Settings(**defaults)


def _trade_idea(
    asset: str = "BTC/USDT",
    action: str = "open_long",
    target_size_pct: float = 0.10,
    conviction: float = 0.7,
) -> TradeIdea:
    return TradeIdea(
        asset=asset,
        action=action,  # type: ignore[arg-type]
        target_size_pct=target_size_pct,
        conviction=conviction,
        combined_rationale="test",
    )


def _ctx(asset: str = "BTC/USDT") -> MarketContext:
    return MarketContext(asset=asset, timeframe="1h")


def _gw_returning(payload: dict) -> MagicMock:
    """Gateway mock that always returns *payload* as JSON in content."""
    gw = MagicMock()
    gw.complete.return_value = LLMResponse(
        provider="test",
        model="test",
        content=json.dumps(payload),
        parsed=payload,
    )
    return gw


# ---------------------------------------------------------------------------
# RiskManager tests
# ---------------------------------------------------------------------------

class TestRiskManager:

    def test_risk_hold_always_passes(self):
        settings = _settings()
        rm = RiskManager(settings)
        broker = PaperBroker(10_000)
        idea = _trade_idea(action="hold")
        order = rm.evaluate(idea, broker, mark_price=50_000.0, equity_start_of_day=10_000.0)
        assert not order.veto

    def test_risk_close_always_passes(self):
        settings = _settings()
        rm = RiskManager(settings)
        broker = PaperBroker(10_000)
        idea = _trade_idea(action="close")
        order = rm.evaluate(idea, broker, mark_price=50_000.0, equity_start_of_day=10_000.0)
        assert not order.veto

    def test_risk_killswitch(self):
        settings = _settings(max_daily_drawdown_pct=0.05)
        rm = RiskManager(settings)
        broker = PaperBroker(10_000)
        broker._balance = 9_400  # 6% drawdown from 10 000
        idea = _trade_idea(action="open_long")
        order = rm.evaluate(idea, broker, mark_price=50_000.0, equity_start_of_day=10_000.0)
        assert order.veto
        assert "Kill-switch" in order.veto_reason

    def test_risk_max_positions_veto(self):
        settings = _settings(max_open_positions=5)
        rm = RiskManager(settings)
        broker = PaperBroker(100_000, fee_pct=0.0, slippage_pct=0.0)
        # Fill up 5 positions using different assets
        assets = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"]
        for asset in assets:
            broker.place_order(asset, "long", 0.05, 100.0, 90.0, 110.0)
        assert len(broker.get_positions()) == 5

        # Use the current balance as equity_start_of_day so the kill-switch
        # does not fire before we reach the max-positions check.
        equity_now = broker.get_balance()

        # Try to open a 6th
        sixth_idea = _trade_idea(asset="DOGE/USDT", action="open_long")
        order = rm.evaluate(sixth_idea, broker, mark_price=1.0, equity_start_of_day=equity_now)
        assert order.veto
        assert "Max open positions" in order.veto_reason

    def test_risk_size_capped(self):
        settings = _settings(max_position_pct=0.20)
        rm = RiskManager(settings)
        broker = PaperBroker(10_000)
        idea = _trade_idea(action="open_long", target_size_pct=0.50)
        order = rm.evaluate(idea, broker, mark_price=50_000.0, equity_start_of_day=10_000.0)
        assert not order.veto
        assert order.size_pct == pytest.approx(0.20)

    def test_risk_sl_tp_prices_correct(self):
        settings = _settings(default_sl_pct=0.03, default_tp_pct=0.06)
        rm = RiskManager(settings)
        broker = PaperBroker(10_000)
        idea = _trade_idea(action="open_long", target_size_pct=0.10)
        mark = 50_000.0
        order = rm.evaluate(idea, broker, mark_price=mark, equity_start_of_day=10_000.0)
        assert not order.veto
        assert order.sl_price == pytest.approx(mark * 0.97)   # 48 500
        assert order.tp_price == pytest.approx(mark * 1.06)   # 53 000

    def test_risk_no_flip_veto(self):
        settings = _settings()
        rm = RiskManager(settings)
        broker = PaperBroker(10_000, fee_pct=0.0, slippage_pct=0.0)
        # Open a SHORT for BTC/USDT
        broker.place_order("BTC/USDT", "short", 0.10, 50_000.0, 51_500.0, 47_000.0)
        # Use the current balance as equity_start_of_day so the kill-switch
        # does not fire before we reach the no-flip check.
        equity_now = broker.get_balance()
        # Now try to go LONG on the same asset
        idea = _trade_idea(asset="BTC/USDT", action="open_long", target_size_pct=0.10)
        order = rm.evaluate(idea, broker, mark_price=50_000.0, equity_start_of_day=equity_now)
        assert order.veto
        assert "Opposite position" in order.veto_reason


# ---------------------------------------------------------------------------
# PortfolioManagerAgent tests
# ---------------------------------------------------------------------------

class TestPortfolioManager:

    _weights: dict = {
        "technical": 0.30,
        "forecast": 0.20,
        "sentiment": 0.20,
        "onchain": 0.15,
        "news": 0.15,
    }

    def _views(self, signal: str, n: int = 5, confidence: float = 0.8) -> list[AgentView]:
        agents = ["technical", "forecast", "sentiment", "onchain", "news"]
        return [
            AgentView(
                agent=agents[i % len(agents)],
                asset="BTC/USDT",
                signal=signal,
                confidence=confidence,
                rationale="test",
            )
            for i in range(n)
        ]

    def test_pm_aggregate_all_long(self):
        payload = {
            "action": "open_long",
            "target_size_pct": 0.15,
            "conviction": 0.8,
            "combined_rationale": "bullish consensus",
        }
        pm = PortfolioManagerAgent(_gw_returning(payload), self._weights)
        idea = pm.aggregate(self._views("long"), "BTC/USDT", _ctx())
        assert idea.action == "open_long"

    def test_pm_aggregate_fallback_on_error(self):
        gw = MagicMock()
        gw.complete.side_effect = Exception("network failure")
        pm = PortfolioManagerAgent(gw, self._weights)
        # All long with confidence=0.8 → norm_score > 0.2 → fallback open_long
        idea = pm.aggregate(self._views("long", confidence=0.8), "BTC/USDT", _ctx())
        assert idea.action == "open_long"

    def test_pm_aggregate_mixed_signals_hold(self):
        payload = {
            "action": "hold",
            "target_size_pct": 0.0,
            "conviction": 0.1,
            "combined_rationale": "mixed signals",
        }
        pm = PortfolioManagerAgent(_gw_returning(payload), self._weights)
        long_views = self._views("long", n=3)
        short_views = self._views("short", n=3)
        idea = pm.aggregate(long_views + short_views, "BTC/USDT", _ctx())
        assert idea.action == "hold"

    def test_pm_size_clamped(self):
        payload = {
            "action": "open_long",
            "target_size_pct": 0.99,   # above the 0.25 cap in PortfolioManagerAgent
            "conviction": 0.9,
            "combined_rationale": "aggressive",
        }
        pm = PortfolioManagerAgent(_gw_returning(payload), self._weights)
        idea = pm.aggregate(self._views("long"), "BTC/USDT", _ctx())
        assert idea.target_size_pct <= 0.25


# ---------------------------------------------------------------------------
# Orchestrator integration tests
# ---------------------------------------------------------------------------

class TestOrchestrator:

    def _make_session(self):
        engine = init_db("sqlite:///:memory:")
        Session = sessionmaker(bind=engine)
        return Session()

    def _make_settings(self) -> Settings:
        return Settings(assets=["BTC/USDT", "ETH/USDT", "SOL/USDT"])

    def _make_gateway(self) -> MagicMock:
        """
        Return a gateway mock whose complete() always produces a valid neutral
        specialist response (JSON with signal/confidence/rationale) for the
        specialist agents, and a hold response for the PortfolioManager.

        The PortfolioManager calls gateway.complete() with a user message that
        contains an ``asset`` field (JSON dict), while specialist agents pass
        the MarketContext as a string. We always return a JSON string that
        satisfies both callers.
        """
        # PM payload — valid for PortfolioManager
        pm_payload = {
            "action": "hold",
            "target_size_pct": 0.0,
            "conviction": 0.1,
            "combined_rationale": "neutral",
            # Specialist agents also parse these fields
            "signal": "neutral",
            "confidence": 0.5,
            "rationale": "no clear signal",
            # Extra keys specialist agents may look for (ignored if absent)
            "key_levels": {},
            "expected_move_pct": 0.0,
            "uncertainty": "medium",
            "regime": "neutral",
            "contrarian": False,
            "headline_risk": "low",
            "summary": "quiet market",
        }
        gw = MagicMock()
        gw.complete.return_value = LLMResponse(
            provider="test",
            model="test",
            content=json.dumps(pm_payload),
            parsed=pm_payload,
        )
        return gw

    def test_orchestrator_stock_cycle(self):
        """Stock asset is processed when market is open; crypto-only agents skipped."""
        session = self._make_session()
        settings = Settings(
            assets=["AAPL"],
            asset_classes=["AAPL:stock"],
        )
        broker = PaperBroker(10_000)
        gateway = self._make_gateway()

        dummy_ctx = MarketContext(asset="AAPL", timeframe="1h")

        with (
            patch("app.orchestrator.build_context", return_value=dummy_ctx),
            patch("app.orchestrator.is_market_open", return_value=True),
        ):
            results = run_cycle(settings, broker, gateway, session)

        assert len(results) == 1
        assert results[0]["asset"] == "AAPL"
        assert "action" in results[0]

    def test_orchestrator_stock_market_closed(self):
        """Stock asset skipped with veto when market is closed."""
        session = self._make_session()
        settings = Settings(
            assets=["AAPL"],
            asset_classes=["AAPL:stock"],
        )
        broker = PaperBroker(10_000)
        gateway = self._make_gateway()

        with patch("app.orchestrator.is_market_open", return_value=False):
            results = run_cycle(settings, broker, gateway, session)

        assert len(results) == 1
        assert results[0]["veto"] is True
        assert "closed" in results[0]["veto_reason"].lower()

    def test_orchestrator_single_cycle(self):
        session = self._make_session()
        settings = self._make_settings()
        broker = PaperBroker(10_000)
        gateway = self._make_gateway()

        dummy_ctx = MarketContext(asset="BTC/USDT", timeframe="1h")

        with patch("app.orchestrator.build_context", return_value=dummy_ctx):
            results = run_cycle(settings, broker, gateway, session)

        # One result per asset
        assert len(results) == 3
        for r in results:
            assert "asset" in r
            assert "action" in r
            assert "balance" in r

        # Decisions should be persisted
        session.commit()
        decisions = session.query(Decision).all()
        assert len(decisions) == 3
