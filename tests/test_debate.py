"""Tests for the bull-vs-bear debate feature (LLM debate + deterministic proxy)."""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
from sqlalchemy.orm import sessionmaker

from app.agents.base import AgentView
from app.agents.debate import (
    DebateAgent,
    DebateTranscript,
    _extract_argument,
    _extract_sides,
    apply_debate_proxy,
    debate_conviction_factor,
    is_borderline,
)
from app.agents.portfolio_manager import PortfolioManagerAgent, TradeIdea
from app.backtest import run_backtest
from app.config import Settings
from app.data.context import MarketContext
from app.llm.providers.base import LLMResponse
from app.persistence.models import init_db
from app.persistence.repo import get_recent_debates, save_debate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _view(agent: str, signal: str, conf: float) -> AgentView:
    return AgentView(
        agent=agent, asset="BTC/USDT", signal=signal, confidence=conf, rationale="t"
    )


def _ctx() -> MarketContext:
    return MarketContext(asset="BTC/USDT", timeframe="1h", indicators={"rsi": 55.0})


def _debate_gateway() -> MagicMock:
    gw = MagicMock()
    gw.complete.return_value = LLMResponse(
        provider="mock", model="mock",
        content='{"bull": "bull thesis", "bear": "bear thesis"}',
        parsed={"bull": "bull thesis", "bear": "bear thesis"},
    )
    return gw


WEIGHTS = {
    "technical": 0.35, "forecast": 0.20, "sentiment": 0.20,
    "onchain": 0.15, "news": 0.10,
}


def _make_ohlcv(n: int = 200) -> pd.DataFrame:
    np.random.seed(42)
    close = 50_000 + np.cumsum(np.random.randn(n) * 100)
    df = pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "volume": np.random.uniform(100, 1_000, n),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="1h"),
    )
    df.index.name = "timestamp"
    return df


# ---------------------------------------------------------------------------
# LLM debate (mocked gateway)
# ---------------------------------------------------------------------------


def test_debate_produces_transcript():
    views = [_view("technical", "long", 0.8), _view("forecast", "short", 0.6)]
    gw = _debate_gateway()
    agent = DebateAgent(gw, rounds=1)
    transcript = agent.run(views, _ctx())
    assert isinstance(transcript, DebateTranscript)
    assert len(transcript.turns) == 2  # bull + bear, 1 round
    assert transcript.turns[0].role == "bull"
    assert transcript.turns[1].role == "bear"
    assert transcript.bull_summary == "bull thesis"
    assert transcript.bear_summary == "bear thesis"
    # Combined prompt: both sides argued in a SINGLE LLM call
    assert gw.complete.call_count == 1


def test_debate_two_rounds():
    gw = _debate_gateway()
    agent = DebateAgent(gw, rounds=2)
    transcript = agent.run([_view("technical", "long", 0.8)], _ctx())
    assert len(transcript.turns) == 4
    assert [t.round for t in transcript.turns] == [1, 1, 2, 2]
    assert gw.complete.call_count == 2  # one combined call per round


def test_debate_rounds_clamped():
    assert DebateAgent(_debate_gateway(), rounds=99).rounds == 2
    assert DebateAgent(_debate_gateway(), rounds=0).rounds == 1


def test_debate_survives_llm_failure():
    gw = MagicMock()
    gw.complete.side_effect = RuntimeError("provider down")
    transcript = DebateAgent(gw, rounds=1).run([_view("technical", "long", 0.8)], _ctx())
    assert transcript.turns == []


def test_extract_argument_variants():
    assert _extract_argument('{"argument": "abc"}') == "abc"
    assert _extract_argument('```json\n{"argument": "abc"}\n```') == "abc"
    assert _extract_argument("plain text") == "plain text"
    assert len(_extract_argument("x" * 5000)) <= 900


def test_extract_sides_variants():
    assert _extract_sides('{"bull": "up", "bear": "down"}') == ("up", "down")
    assert _extract_sides("", {"bull": "up", "bear": "down"}) == ("up", "down")
    assert _extract_sides('```json\n{"bull": "up", "bear": "down"}\n```') == ("up", "down")
    assert _extract_sides(
        '{"bull_argument": "up", "bear_argument": "down"}'
    ) == ("up", "down")
    assert _extract_sides("not json") == ("", "")
    bull, bear = _extract_sides('{"bull": "%s", "bear": "b"}' % ("x" * 5000))
    assert len(bull) <= 900
    assert bear == "b"


def test_is_borderline_band():
    # Strong one-sided consensus → not borderline → debate can be skipped
    strong = [_view("technical", "long", 0.9), _view("forecast", "long", 0.9)]
    assert not is_borderline(strong, WEIGHTS, low=0.05, high=0.35)
    # Mixed/weak signal → borderline → debate should run
    mixed = [_view("technical", "long", 0.6), _view("forecast", "short", 0.5)]
    assert is_borderline(mixed, WEIGHTS, low=0.05, high=0.35)
    # Fully neutral (score ~0) → below the band → skip
    neutral = [_view("technical", "neutral", 0.5)]
    assert not is_borderline(neutral, WEIGHTS, low=0.05, high=0.35)


def test_pm_judge_receives_transcript():
    """When a transcript is passed, the PM user message must include it."""
    gw = MagicMock()
    gw.complete.return_value = LLMResponse(
        provider="mock", model="mock",
        content='{"action":"hold","target_size_pct":0.0,"conviction":0.2,'
                '"combined_rationale":"judged"}',
        parsed={"action": "hold"},
    )
    pm = PortfolioManagerAgent(gw, weights=WEIGHTS)
    transcript = DebateTranscript(
        asset="BTC/USDT",
        turns=[{"role": "bull", "round": 1, "argument": "up"}],
        bull_summary="up",
    )
    idea = pm.aggregate([_view("technical", "long", 0.8)], "BTC/USDT", _ctx(),
                        debate=transcript)
    assert idea.action == "hold"
    user_msg = gw.complete.call_args.kwargs["user"]
    assert "debate_transcript" in user_msg
    assert '"argument": "up"' in user_msg


# ---------------------------------------------------------------------------
# Deterministic proxy
# ---------------------------------------------------------------------------


def test_factor_one_sided_is_neutral():
    views = [_view("technical", "long", 0.9), _view("news", "neutral", 0.1)]
    assert debate_conviction_factor(views, WEIGHTS) == 1.0


def test_factor_no_directional_views_is_neutral():
    views = [_view("news", "neutral", 0.1), _view("onchain", "neutral", 0.1)]
    assert debate_conviction_factor(views, WEIGHTS) == 1.0


def test_factor_split_is_penalised():
    # Equal weighted strength on both sides → full disagreement → max penalty
    views = [_view("technical", "long", 0.8), _view("technical", "short", 0.8)]
    factor = debate_conviction_factor(views, WEIGHTS, max_penalty=0.5)
    assert abs(factor - 0.5) < 1e-9


def test_factor_partial_disagreement_between_bounds():
    views = [_view("technical", "long", 0.9), _view("forecast", "short", 0.4)]
    factor = debate_conviction_factor(views, WEIGHTS, max_penalty=0.5)
    assert 0.5 < factor < 1.0


def test_proxy_reduces_conviction_on_conflict():
    views = [_view("technical", "long", 0.8), _view("forecast", "short", 0.7)]
    idea = TradeIdea(
        asset="BTC/USDT", action="open_long", target_size_pct=0.10,
        conviction=0.6, combined_rationale="r",
    )
    adjusted = apply_debate_proxy(idea, views, WEIGHTS)
    assert adjusted.conviction < idea.conviction
    assert adjusted.target_size_pct < idea.target_size_pct
    assert "debate proxy" in adjusted.combined_rationale


def test_proxy_unchanged_when_one_sided():
    views = [_view("technical", "long", 0.8), _view("news", "neutral", 0.1)]
    idea = TradeIdea(
        asset="BTC/USDT", action="open_long", target_size_pct=0.10,
        conviction=0.6, combined_rationale="r",
    )
    adjusted = apply_debate_proxy(idea, views, WEIGHTS)
    assert adjusted is idea  # untouched object → behaviour identical


def test_proxy_downgrades_weak_open_to_hold():
    views = [_view("technical", "long", 0.8), _view("technical", "short", 0.8)]
    idea = TradeIdea(
        asset="BTC/USDT", action="open_long", target_size_pct=0.10,
        conviction=0.2, combined_rationale="r",
    )
    adjusted = apply_debate_proxy(idea, views, WEIGHTS, max_penalty=0.5)
    assert adjusted.action == "hold"
    assert adjusted.target_size_pct == 0.0


# ---------------------------------------------------------------------------
# Flag OFF ⇒ backtest identical to today
# ---------------------------------------------------------------------------


def test_backtest_flag_off_identical():
    df = _make_ohlcv(200)
    base = Settings()
    base.debate_enabled = False
    off = run_backtest("BTC/USDT", "1h", df, base, MagicMock(), window=100,
                       deterministic=True, forecast_every=0)
    default = run_backtest("BTC/USDT", "1h", df, Settings(), MagicMock(), window=100,
                           deterministic=True, forecast_every=0)
    assert off.summary() == default.summary()
    assert off.equity_curve == default.equity_curve


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def test_save_and_load_debate():
    engine = init_db("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()
    save_debate(
        session, decision_id=None, asset="BTC/USDT",
        bull_summary="up", bear_summary="down",
        transcript=[{"role": "bull", "round": 1, "argument": "up"}],
    )
    session.flush()
    debates = get_recent_debates(session)
    assert len(debates) == 1
    assert debates[0]["bull_summary"] == "up"
    assert debates[0]["transcript"][0]["role"] == "bull"
