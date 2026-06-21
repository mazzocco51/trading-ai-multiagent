from __future__ import annotations

import pandas as pd


def get_ohlcv(asset: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    try:
        import ccxt

        exchange = ccxt.binance({"enableRateLimit": True})
        raw = exchange.fetch_ohlcv(asset, timeframe, limit=limit)
        df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp")
        return df
    except Exception:
        return empty
