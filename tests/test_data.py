from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd

from app.data.indicators import compute_indicators
from app.data.news import get_news_headlines
from app.data.sentiment import get_fear_and_greed
from app.data.whale import get_whale_events


def _make_ohlcv(n: int = 50) -> pd.DataFrame:
    import numpy as np

    rng = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    close = 50_000 + np.cumsum(np.random.randn(n) * 100)
    return pd.DataFrame(
        {
            "open": close - 50,
            "high": close + 100,
            "low": close - 100,
            "close": close,
            "volume": 10.0,
        },
        index=rng,
    )


def test_compute_indicators_on_known_series():
    df = _make_ohlcv(50)
    result = compute_indicators(df)
    assert result["rsi"] is not None
    assert 0 <= result["rsi"] <= 100
    assert isinstance(result["pivot"], float)
    assert result["r1"] > result["pivot"] > result["s1"]


def test_compute_indicators_empty_df():
    result = compute_indicators(pd.DataFrame())
    assert all(v is None for v in result.values())


def test_fear_and_greed_success(monkeypatch):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"data": [{"value": "42", "value_classification": "Fear"}]}
    mock_resp.raise_for_status = MagicMock()
    monkeypatch.setattr("httpx.get", lambda *a, **kw: mock_resp)
    result = get_fear_and_greed()
    assert result["value"] == 42
    assert result["degraded"] is False


def test_fear_and_greed_failure(monkeypatch):
    monkeypatch.setattr("httpx.get", lambda *a, **kw: (_ for _ in ()).throw(Exception("timeout")))
    result = get_fear_and_greed()
    assert result["degraded"] is True
    assert result["value"] is None


def test_whale_no_key():
    assert get_whale_events("") == []


def test_news_failure(monkeypatch):
    monkeypatch.setattr(
        "httpx.get", lambda *a, **kw: (_ for _ in ()).throw(Exception("conn error"))
    )
    result = get_news_headlines("BTC/USDT")
    assert result == []


def test_build_context_degraded(monkeypatch):
    from app.data.context import build_context

    monkeypatch.setattr("app.data.context.get_ohlcv", lambda *a, **kw: pd.DataFrame())
    monkeypatch.setattr(
        "app.data.context.get_fear_and_greed", lambda: (_ for _ in ()).throw(Exception("fail"))
    )
    ctx = build_context("BTC/USDT", "1h")
    assert len(ctx.degraded_sources) >= 1
    assert ctx.asset == "BTC/USDT"
