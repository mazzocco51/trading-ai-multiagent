from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd

# ---------------------------------------------------------------------------
# get_stock_ohlcv
# ---------------------------------------------------------------------------

def _make_yf_df() -> pd.DataFrame:
    """Build a minimal yfinance-style DataFrame."""
    idx = pd.date_range("2024-01-02 14:00", periods=5, freq="h", tz="America/New_York")
    df = pd.DataFrame(
        {
            "Open": [150.0, 151.0, 152.0, 151.5, 153.0],
            "High": [151.5, 152.5, 153.0, 152.0, 154.0],
            "Low": [149.5, 150.5, 151.5, 151.0, 152.5],
            "Close": [151.0, 152.0, 151.5, 153.0, 153.5],
            "Volume": [1_000, 1_100, 900, 1_200, 800],
        },
        index=idx,
    )
    return df


def test_get_stock_ohlcv_returns_dataframe():
    """Successful yfinance fetch → correct column schema and UTC index."""
    from app.data.stocks import get_stock_ohlcv

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _make_yf_df()

    with patch("yfinance.Ticker", return_value=mock_ticker):
        df = get_stock_ohlcv("AAPL", timeframe="1h", limit=200)

    assert not df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.tz is not None  # UTC-aware


def test_get_stock_ohlcv_failure():
    """yfinance raises an exception → returns empty DataFrame."""
    from app.data.stocks import get_stock_ohlcv

    with patch("yfinance.Ticker", side_effect=RuntimeError("network error")):
        df = get_stock_ohlcv("AAPL")

    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]


# ---------------------------------------------------------------------------
# is_market_open
# ---------------------------------------------------------------------------

def _make_et_dt(year: int, month: int, day: int, hour: int, minute: int):
    import pytz

    et = pytz.timezone("America/New_York")
    return et.localize(datetime(year, month, day, hour, minute, 0))


def test_is_market_open_weekend():
    """Saturday → market is closed."""
    from app.data.stocks import is_market_open

    # 2024-01-06 is a Saturday
    saturday = _make_et_dt(2024, 1, 6, 11, 0)
    with patch("app.data.stocks.datetime") as mock_dt:
        mock_dt.now.return_value = saturday
        assert is_market_open() is False


def test_is_market_open_hours():
    """Tuesday 10:00 ET → open; Tuesday 08:00 ET → closed."""
    from app.data.stocks import is_market_open

    # 2024-01-02 is a Tuesday
    open_time = _make_et_dt(2024, 1, 2, 10, 0)
    closed_time = _make_et_dt(2024, 1, 2, 8, 0)

    with patch("app.data.stocks.datetime") as mock_dt:
        mock_dt.now.return_value = open_time
        assert is_market_open() is True

    with patch("app.data.stocks.datetime") as mock_dt:
        mock_dt.now.return_value = closed_time
        assert is_market_open() is False
