from __future__ import annotations

import json
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agents.reflection import ReflectionAgent
from app.config import Settings
from app.data.context import MarketContext
from app.llm.providers.base import LLMResponse
from app.orchestrator import run_cycle
from app.persistence.models import Base
from app.persistence.repo import add_lessons, get_recent_lessons


def _make_session() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _llm_response(content: str) -> LLMResponse:
    return LLMResponse(provider="mock", model="m", content=content, parsed={})


# --------------------------------------------------------------------------- #
# B1 — lesson storage
# --------------------------------------------------------------------------- #
def test_add_and_get_lessons():
    session = _make_session()
    add_lessons(session, ["first", "second", "third"])
    session.commit()

    lessons = get_recent_lessons(session)
    assert lessons == ["third", "second", "first"]  # newest first


def test_get_lessons_limit():
    session = _make_session()
    add_lessons(session, [f"lesson-{i}" for i in range(10)])
    session.commit()

    lessons = get_recent_lessons(session, limit=3)
    assert len(lessons) == 3


# --------------------------------------------------------------------------- #
# B2 — reflection agent
# --------------------------------------------------------------------------- #
def test_reflection_agent_returns_lessons():
    gateway = MagicMock()
    gateway.complete.return_value = _llm_response(
        json.dumps({"lessons": ["rule1", "rule2", "rule3"]})
    )
    agent = ReflectionAgent(gateway)
    lessons = agent.reflect(recent_trades=[{"asset": "BTC/USDT"}], current_lessons=[])

    assert lessons == ["rule1", "rule2", "rule3"]
    assert all(isinstance(le, str) for le in lessons)


def test_reflection_agent_gateway_failure():
    gateway = MagicMock()
    gateway.complete.side_effect = Exception("provider down")
    agent = ReflectionAgent(gateway)

    assert agent.reflect(recent_trades=[], current_lessons=[]) == []


# --------------------------------------------------------------------------- #
# PortfolioManager — lessons injected into payload
# --------------------------------------------------------------------------- #
def test_pm_receives_lessons_in_payload():
    from app.agents.portfolio_manager import PortfolioManagerAgent

    captured: dict = {}

    def _capture(system: str, user: str) -> LLMResponse:
        captured["user"] = user
        return _llm_response(
            json.dumps(
                {
                    "action": "hold",
                    "target_size_pct": 0.0,
                    "conviction": 0.0,
                    "combined_rationale": "ok",
                }
            )
        )

    gateway = MagicMock()
    gateway.complete.side_effect = _capture

    pm = PortfolioManagerAgent(gateway, weights={"technical": 1.0})
    ctx = MarketContext(asset="BTC/USDT", timeframe="1h")
    pm.aggregate([], "BTC/USDT", ctx, lessons=["rule1"])

    assert "rule1" in captured["user"]
    payload = json.loads(captured["user"])
    assert payload["lessons_learned"] == ["rule1"]


# --------------------------------------------------------------------------- #
# B3 — orchestrator reflection trigger
# --------------------------------------------------------------------------- #
def _make_settings() -> Settings:
    settings = Settings()
    settings.assets = []  # skip per-asset loop, isolate the trigger
    settings.reflection_every_n_trades = 5
    settings.asset_classes = []
    return settings


def _fake_broker(n_trades: int) -> MagicMock:
    broker = MagicMock()
    broker.trade_history = [{"asset": "BTC/USDT", "pnl": 1.0} for _ in range(n_trades)]
    broker.get_equity.return_value = 10_000.0
    broker.get_balance.return_value = 10_000.0
    broker.last_reflected_count = 0
    return broker


def test_reflection_not_triggered_wrong_count():
    session = _make_session()
    settings = _make_settings()
    broker = _fake_broker(4)  # 4 % 5 != 0

    gateway = MagicMock()
    gateway.complete.return_value = _llm_response(
        json.dumps({"lessons": ["should-not-store"]})
    )

    run_cycle(settings, broker, gateway, session)
    session.commit()

    assert get_recent_lessons(session) == []


def test_reflection_triggered_at_multiple():
    session = _make_session()
    settings = _make_settings()
    broker = _fake_broker(5)  # 5 % 5 == 0

    gateway = MagicMock()
    gateway.complete.return_value = _llm_response(
        json.dumps({"lessons": ["rule-a", "rule-b", "rule-c"]})
    )

    run_cycle(settings, broker, gateway, session)
    session.commit()

    assert get_recent_lessons(session) == ["rule-c", "rule-b", "rule-a"]


def test_reflection_not_refired_same_batch():
    """Edge-trigger: a count already reflected must not reflect again."""
    session = _make_session()
    settings = _make_settings()
    broker = _fake_broker(5)
    broker.last_reflected_count = 5  # already reflected this batch

    gateway = MagicMock()
    gateway.complete.return_value = _llm_response(
        json.dumps({"lessons": ["should-not-store"]})
    )

    run_cycle(settings, broker, gateway, session)
    session.commit()

    assert get_recent_lessons(session) == []
