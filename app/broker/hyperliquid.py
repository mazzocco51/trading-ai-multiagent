from __future__ import annotations

from typing import Literal

from app.broker.base import Broker, OrderResult, Position

# To enable: set BROKER=hyperliquid_testnet in env and install hyperliquid-python-sdk


class HyperliquidBroker(Broker):
    def __init__(self, api_key: str, api_secret: str, testnet: bool = True) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet

    def get_balance(self) -> float:
        raise NotImplementedError("HyperliquidBroker not yet implemented")

    def get_positions(self) -> list[Position]:
        raise NotImplementedError("HyperliquidBroker not yet implemented")

    def place_order(
        self,
        asset: str,
        side: Literal["long", "short"],
        size_pct: float,
        mark_price: float,
        sl_price: float,
        tp_price: float,
    ) -> OrderResult:
        raise NotImplementedError("HyperliquidBroker not yet implemented")

    def close_position(self, asset: str, mark_price: float) -> bool:
        raise NotImplementedError("HyperliquidBroker not yet implemented")

    def mark_price(self, asset: str) -> float:
        raise NotImplementedError("HyperliquidBroker not yet implemented")
