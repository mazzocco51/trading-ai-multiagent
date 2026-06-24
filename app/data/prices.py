from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

_EXCHANGE_ORDER = ["kraken", "coinbase", "kucoin", "binance"]
_USD_EXCHANGES = {"kraken", "coinbase"}


def _map_symbol(asset: str, exchange_id: str) -> str:
    if exchange_id in _USD_EXCHANGES and asset.endswith("/USDT"):
        return asset[:-4] + "USD"
    return asset


def get_ohlcv(asset: str, timeframe: str, limit: int = 200) -> pd.DataFrame:
    empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    try:
        import ccxt
    except ImportError:
        logger.warning("[prices] ccxt not installed; returning empty DataFrame")
        return empty

    for exchange_id in _EXCHANGE_ORDER:
        try:
            exchange_cls = getattr(ccxt, exchange_id)
            exchange = exchange_cls({"enableRateLimit": True})
            symbol = _map_symbol(asset, exchange_id)
            raw = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            if not raw:
                continue
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df = df.set_index("timestamp")
            logger.info("[prices] served by %s", exchange_id)
            return df
        except Exception as exc:  # noqa: BLE001
            logger.debug("[prices] %s failed: %s", exchange_id, exc)
            continue

    logger.warning("[prices] all exchanges failed for %s; returning empty DataFrame", asset)
    return empty
