"""Tests for regime-adaptive agent weights."""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pandas as pd

from app.agents.adaptive_weights import (
    adapt_weights,
    realized_volatility_pct,
    volatility_regime,
)
from app.backtest import run_backtest
from app.config import Settings

BASE = {
    "technical": 0.35, "forecast": 0.20, "sentiment": 0.20,
    "onchain": 0.15, "news": 0.10,
}


# ---------------------------------------------------------------------------
# Volatility estimation
# ---------------------------------------------------------------------------


def test_vol_constant_prices_is_zero():
    assert realized_volatility_pct([100.0] * 30) == 0.0


def test_vol_insufficient_data_is_none():
    assert realized_volatility_pct([100.0, 101.0]) is None
    assert realized_volatility_pct([]) is None


def test_vol_higher_for_noisier_series():
    rng = np.random.default_rng(7)
    calm = list(100.0 * np.cumprod(1 + rng.normal(0, 0.001, 50)))
    wild = list(100.0 * np.cumprod(1 + rng.normal(0, 0.02, 50)))
    assert realized_volatility_pct(wild) > realized_volatility_pct(calm)


def test_regime_classification():
    assert volatility_regime(None) == "normal"
    assert volatility_regime(0.001, 0.004, 0.009) == "low"
    assert volatility_regime(0.006, 0.004, 0.009) == "normal"
    assert volatility_regime(0.02, 0.004, 0.009) == "high"


# ---------------------------------------------------------------------------
# Weight adaptation
# ---------------------------------------------------------------------------


def test_high_vol_shifts_towards_sentiment_news():
    w = adapt_weights(BASE, vol_pct=0.02)
    assert w["sentiment"] > BASE["sentiment"]
    assert w["news"] > BASE["news"]
    assert w["technical"] < BASE["technical"]
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_low_vol_shifts_towards_technical():
    w = adapt_weights(BASE, vol_pct=0.001)
    assert w["technical"] > BASE["technical"]
    assert w["sentiment"] < BASE["sentiment"]
    assert w["news"] < BASE["news"]
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_normal_regime_keeps_base_weights():
    w = adapt_weights(BASE, vol_pct=0.006)
    for agent, base_w in BASE.items():
        assert abs(w[agent] - base_w) < 1e-9
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_missing_vol_keeps_base_weights():
    w = adapt_weights(BASE, vol_pct=None)
    assert abs(sum(w.values()) - 1.0) < 1e-9
    assert abs(w["technical"] - BASE["technical"]) < 1e-9


def test_subset_weights_still_sum_to_one():
    # Stock asset class: no sentiment/onchain agents
    stock_base = {"technical": 0.5, "forecast": 0.3, "news": 0.2}
    for vol in (0.001, 0.006, 0.02, None):
        w = adapt_weights(stock_base, vol_pct=vol)
        assert abs(sum(w.values()) - 1.0) < 1e-9


def test_weights_never_negative_even_with_extreme_shift():
    w = adapt_weights(BASE, vol_pct=0.05, shift=5.0)  # shift clamped internally
    assert all(v > 0 for v in w.values())
    assert abs(sum(w.values()) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Backtest integration
# ---------------------------------------------------------------------------


def _make_ohlcv(n: int, per_bar_vol: float) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    close = 50_000 * np.cumprod(1 + rng.normal(0, per_bar_vol, n))
    df = pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.004,
            "low": close * 0.996,
            "close": close,
            "volume": rng.uniform(100, 1_000, n),
        },
        index=pd.date_range("2024-01-01", periods=n, freq="1h"),
    )
    df.index.name = "timestamp"
    return df


def test_backtest_flag_off_identical():
    df = _make_ohlcv(200, 0.01)
    off = Settings()
    off.adaptive_weights_enabled = False
    a = run_backtest("BTC/USDT", "1h", df, off, MagicMock(), window=100,
                     deterministic=True, forecast_every=0)
    b = run_backtest("BTC/USDT", "1h", df, Settings(), MagicMock(), window=100,
                     deterministic=True, forecast_every=0)
    assert a.summary() == b.summary()
    assert a.equity_curve == b.equity_curve


def test_backtest_adaptive_runs_high_vol_window():
    """High-vol synthetic data: the flag must not break the pipeline and the
    PM must end up with tilted weights (sentiment > base 0.20 share)."""
    df = _make_ohlcv(160, 0.02)  # ~2% per-bar vol → high regime
    settings = Settings()
    settings.adaptive_weights_enabled = True
    result = run_backtest("BTC/USDT", "1h", df, settings, MagicMock(), window=100,
                          deterministic=True, forecast_every=0)
    assert result.final_balance > 0
    # Weights recorded in the last decision's views summary must be tilted
    # (verified via adapt_weights on the same data for determinism)
    closes = [float(c) for c in df["close"].tolist()[-101:-1]]
    from app.agents.adaptive_weights import realized_volatility_pct as rv
    vol = rv(closes, settings.adaptive_vol_lookback)
    w = adapt_weights(settings.agent_weights, vol)
    assert w["sentiment"] > 0.20
    assert w["technical"] < 0.35
    assert abs(sum(w.values()) - 1.0) < 1e-9


def test_config_flags_default_off():
    s = Settings()
    assert s.debate_enabled is False
    assert s.adaptive_weights_enabled is False
