"""PaperStockBroker — thin stub for US equity paper trading.

This is a stub implementation. The broker reuses PaperBroker's order book and
position management, but overrides mark_price() to fetch the latest quote from
yfinance instead of relying on a manually-set mock price.

TODO: implement full Alpaca paper trading (REST + WebSocket) as a follow-up.
      Alpaca offers a free paper-trading environment at
      https://alpaca.markets/docs/trading/ with real-time data via APCA-API-KEY-ID.
"""
from __future__ import annotations

import logging

from app.broker.paper import PaperBroker

logger = logging.getLogger(__name__)


class PaperStockBroker(PaperBroker):
    """Paper broker for US equities.  Uses yfinance for mark prices.

    Inherits all order-book logic (place_order, close_position, check_sl_tp,
    export_state, load_state) from PaperBroker unchanged.  Only mark_price()
    is overridden to pull the latest close from yfinance.
    """

    def mark_price(self, asset: str) -> float:
        """Return the latest available close price for *asset* from yfinance.

        Falls back to the mock price (set via set_mock_price) if yfinance
        fails, so unit tests remain fully deterministic.
        """
        try:
            import yfinance as yf

            ticker = yf.Ticker(asset)
            hist = ticker.history(period="2d", interval="1m", auto_adjust=True)
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                logger.debug("mark_price(%s) = %.4f via yfinance", asset, price)
                return price
        except Exception as exc:
            logger.warning("yfinance mark_price failed for %s: %s", asset, exc)

        # Fall back to the parent's mock-price dict
        return super().mark_price(asset)
