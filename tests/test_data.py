from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd

from app.data.indicators import compute_indicators
from app.data.news import get_news_headlines
from app.data.prices import _map_symbol, get_ohlcv
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


# ---------------------------------------------------------------------------
# get_ohlcv fallback chain (A1)
# ---------------------------------------------------------------------------

def _raw_candles():
    return [[1_700_000_000_000, 50000, 51000, 49000, 50500, 1.0]]


def test_symbol_mapping():
    assert _map_symbol("BTC/USDT", "kraken") == "BTC/USD"
    assert _map_symbol("BTC/USDT", "coinbase") == "BTC/USD"
    assert _map_symbol("BTC/USDT", "kucoin") == "BTC/USDT"
    assert _map_symbol("BTC/USDT", "binance") == "BTC/USDT"
    assert _map_symbol("SOL/USDT", "kraken") == "SOL/USD"


def test_get_ohlcv_kraken_first(monkeypatch):
    import ccxt

    mock_exchange = MagicMock()
    mock_exchange.fetch_ohlcv.return_value = _raw_candles()
    monkeypatch.setattr(ccxt, "kraken", lambda *a, **kw: mock_exchange)

    df = get_ohlcv("BTC/USDT", "1h", limit=1)
    assert not df.empty
    mock_exchange.fetch_ohlcv.assert_called_once_with("BTC/USD", "1h", limit=1)


def test_get_ohlcv_fallback_to_kucoin(monkeypatch):
    import ccxt

    failing = MagicMock()
    failing.fetch_ohlcv.side_effect = Exception("blocked")
    ok = MagicMock()
    ok.fetch_ohlcv.return_value = _raw_candles()

    monkeypatch.setattr(ccxt, "kraken", lambda *a, **kw: failing)
    monkeypatch.setattr(ccxt, "coinbase", lambda *a, **kw: failing)
    monkeypatch.setattr(ccxt, "kucoin", lambda *a, **kw: ok)
    monkeypatch.setattr(ccxt, "binance", lambda *a, **kw: failing)

    df = get_ohlcv("BTC/USDT", "1h", limit=1)
    assert not df.empty
    ok.fetch_ohlcv.assert_called_once_with("BTC/USDT", "1h", limit=1)


def test_get_ohlcv_all_fail(monkeypatch):
    import ccxt

    failing = MagicMock()
    failing.fetch_ohlcv.side_effect = Exception("blocked")
    for ex in ("kraken", "coinbase", "kucoin", "binance"):
        monkeypatch.setattr(ccxt, ex, lambda *a, **kw: failing)

    df = get_ohlcv("BTC/USDT", "1h")
    assert df.empty


def test_build_context_degraded(monkeypatch):
    from app.data.context import build_context

    monkeypatch.setattr("app.data.context.get_ohlcv", lambda *a, **kw: pd.DataFrame())
    monkeypatch.setattr(
        "app.data.context.get_fear_and_greed", lambda: (_ for _ in ()).throw(Exception("fail"))
    )
    ctx = build_context("BTC/USDT", "1h")
    assert len(ctx.degraded_sources) >= 1
    assert ctx.asset == "BTC/USDT"
