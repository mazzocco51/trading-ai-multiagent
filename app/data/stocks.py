from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd

logger = logging.getLogger(__name__)

# Mapping from internal timeframe strings to yfinance interval strings
_TF_MAP: dict[str, str] = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "1d": "1d",
    "1wk": "1wk",
    "1mo": "1mo",
}

_EMPTY = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


def get_stock_ohlcv(symbol: str, timeframe: str = "1h", limit: int = 200) -> pd.DataFrame:
    """Fetch OHLCV for a stock symbol via yfinance (no API key needed).

    Returns a DataFrame with columns [open, high, low, close, volume] and a
    UTC DatetimeIndex — same schema as get_ohlcv() in app/data/prices.py.
    Returns an empty DataFrame on any failure.
    """
    try:
        import yfinance as yf

        interval = _TF_MAP.get(timeframe, "1h")

        # yfinance needs a period; derive a reasonable one from limit + interval
        # Use a generous period so we always get at least `limit` bars
        period_map = {
            "1m": "7d",
            "5m": "60d",
            "15m": "60d",
            "30m": "60d",
            "1h": "730d",
            "2h": "730d",
            "4h": "730d",
            "1d": "5y",
            "1wk": "10y",
            "1mo": "10y",
        }
        period = period_map.get(interval, "730d")

        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval, auto_adjust=True)

        if df.empty:
            logger.warning("yfinance returned empty data for %s (interval=%s)", symbol, interval)
            return _EMPTY.copy()

        # Normalise column names to lowercase
        df.columns = [c.lower() for c in df.columns]
        # Keep only the OHLCV columns
        df = df[["open", "high", "low", "close", "volume"]].copy()

        # Ensure UTC index
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        # Honour limit — return the most recent `limit` bars
        df = df.tail(limit)

        logger.info("yfinance: fetched %d bars for %s (interval=%s)", len(df), symbol, interval)
        return df

    except Exception as exc:
        logger.error("get_stock_ohlcv failed for %s: %s", symbol, exc)
        return _EMPTY.copy()


def is_market_open(symbol: str = "AAPL") -> bool:  # noqa: ARG001
    """Return True if the US equity market is currently open (Mon-Fri 09:30-16:00 ET)."""
    import pytz

    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    return market_open <= now <= market_close
