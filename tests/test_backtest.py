"""Tests for the backtest module."""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from app.backtest import (
    BacktestResult,
    _NoLLMGateway,
    run_backtest,
    run_backtest_multi,
)
from app.config import Settings
from app.llm.providers.base import LLMResponse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_gw(action: str = "hold") -> MagicMock:
    """Return a gateway mock whose .complete() always returns a valid PM response.

    Specialist agents will try to parse the same response; the JSON happens to
    be valid for the PM schema so agents that use resp.parsed will get sensible
    values.  Agents that expect "signal" will fall back to "neutral" gracefully
    because the response contains an "action" key, not "signal".
    """
    gw = MagicMock()
    # PM-shaped JSON — agents fall back gracefully when keys are missing
    pm_resp = LLMResponse(
        provider="mock",
        model="mock",
        content=(
            f'{{"action":"{action}","target_size_pct":0.10,'
            f'"conviction":0.6,"combined_rationale":"test",'
            f'"signal":"neutral","confidence":0.5,"rationale":"test","key_levels":{{}}}}'
        ),
        parsed={
            "action": action,
            "target_size_pct": 0.10,
            "conviction": 0.6,
            "combined_rationale": "test",
            "signal": "neutral",
            "confidence": 0.5,
            "rationale": "test",
            "key_levels": {},
        },
    )
    gw.complete.return_value = pm_resp
    return gw


def _make_ohlcv(n: int = 200) -> pd.DataFrame:
    """Synthetic OHLCV data: random walk."""
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
# Core tests
# ---------------------------------------------------------------------------

def test_backtest_returns_result():
    gw = _mock_gw("hold")
    df = _make_ohlcv(150)
    settings = Settings()
    result = run_backtest("BTC/USDT", "1h", df, settings, gw, window=50, step=10)
    assert isinstance(result, BacktestResult)
    assert result.asset == "BTC/USDT"
    assert result.initial_balance == settings.paper_initial_balance
    assert result.final_balance > 0
    assert len(result.equity_curve) > 0


def test_backtest_summary_keys():
    gw = _mock_gw()
    df = _make_ohlcv(150)
    result = run_backtest("BTC/USDT", "1h", df, Settings(), gw, window=50, step=10)
    summary = result.summary()
    for key in [
        "asset",
        "initial_balance",
        "final_balance",
        "pnl",
        "pnl_pct",
        "n_trades",
        "win_rate",
        "max_drawdown_pct",
    ]:
        assert key in summary


def test_backtest_win_rate_bounds():
    gw = _mock_gw()
    df = _make_ohlcv(150)
    result = run_backtest("BTC/USDT", "1h", df, Settings(), gw, window=50, step=10)
    assert 0.0 <= result.win_rate <= 1.0


def test_backtest_max_drawdown_non_negative():
    gw = _mock_gw()
    df = _make_ohlcv(150)
    result = run_backtest("BTC/USDT", "1h", df, Settings(), gw, window=50, step=10)
    assert result.max_drawdown >= 0.0


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

def test_backtest_pnl_consistency():
    gw = _mock_gw("hold")
    df = _make_ohlcv(150)
    result = run_backtest("BTC/USDT", "1h", df, Settings(), gw, window=50, step=10)
    assert abs(result.pnl - (result.final_balance - result.initial_balance)) < 1e-9


def test_backtest_pnl_pct_consistency():
    gw = _mock_gw("hold")
    df = _make_ohlcv(150)
    result = run_backtest("BTC/USDT", "1h", df, Settings(), gw, window=50, step=10)
    expected = result.pnl / result.initial_balance if result.initial_balance else 0.0
    assert abs(result.pnl_pct - expected) < 1e-9


def test_equity_curve_has_step_and_balance():
    gw = _mock_gw()
    df = _make_ohlcv(150)
    result = run_backtest("BTC/USDT", "1h", df, Settings(), gw, window=50, step=10)
    for point in result.equity_curve:
        assert "step" in point
        assert "balance" in point
        assert point["balance"] > 0


def test_backtest_n_trades_non_negative():
    gw = _mock_gw()
    df = _make_ohlcv(150)
    result = run_backtest("BTC/USDT", "1h", df, Settings(), gw, window=50, step=10)
    assert result.n_trades >= 0


# ---------------------------------------------------------------------------
# Multi-asset helper
# ---------------------------------------------------------------------------

def test_run_backtest_multi():
    df = _make_ohlcv(150)
    gw = _mock_gw("hold")
    settings = Settings()
    results = run_backtest_multi(
        assets=["BTC/USDT", "ETH/USDT"],
        timeframe="1h",
        settings=settings,
        gateway=gw,
        df_map={"BTC/USDT": df, "ETH/USDT": df},
        window=50,
        step=10,
    )
    assert len(results) == 2
    assert all(isinstance(r, BacktestResult) for r in results)
    assert results[0].asset == "BTC/USDT"
    assert results[1].asset == "ETH/USDT"


# ---------------------------------------------------------------------------
# Extended metrics (D1)
# ---------------------------------------------------------------------------

def test_profit_factor_positive():
    result = BacktestResult(
        asset="BTC/USDT",
        trades=[{"pnl": 10.0}, {"pnl": 5.0}, {"pnl": -2.0}],
    )
    assert result.profit_factor > 1.0


def test_profit_factor_no_losses():
    result = BacktestResult(
        asset="BTC/USDT",
        trades=[{"pnl": 10.0}, {"pnl": 5.0}],
    )
    assert result.profit_factor == float("inf")


def test_sharpe_flat_equity():
    result = BacktestResult(
        asset="BTC/USDT",
        equity_curve=[{"step": i, "balance": 1000.0} for i in range(10)],
    )
    assert result.sharpe == 0.0


def test_sharpe_positive_trend():
    result = BacktestResult(
        asset="BTC/USDT",
        equity_curve=[
            {"step": i, "balance": 1000.0 * (1.01 ** i)} for i in range(20)
        ],
    )
    assert result.sharpe > 0.0


def test_no_llm_gateway_returns_hold():
    resp = _NoLLMGateway().complete("sys", "usr")
    assert "hold" in resp.content


def test_run_backtest_produces_summary_keys():
    df = _make_ohlcv(120)
    result = run_backtest(
        "BTC/USDT", "1h", df, Settings(), _NoLLMGateway(), window=100, step=1
    )
    summary = result.summary()
    for key in [
        "asset",
        "initial_balance",
        "final_balance",
        "pnl",
        "pnl_pct",
        "n_trades",
        "win_rate",
        "max_drawdown_pct",
        "profit_factor",
        "sharpe",
    ]:
        assert key in summary


def test_btc_bh_return_pct_in_summary():
    result = BacktestResult(asset="BTC/USDT")
    result.btc_bh_return_pct = 12.5
    assert result.summary()["btc_bh_return_pct"] == 12.5
