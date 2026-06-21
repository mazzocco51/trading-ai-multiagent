from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal


@dataclass
class Position:
    asset: str
    side: Literal["long", "short"]
    size: float
    entry_price: float
    sl_price: float
    tp_price: float
    opened_at: str
    size_pct: float = 0.0


@dataclass
class OrderResult:
    success: bool
    order_id: str
    asset: str
    side: Literal["long", "short"]
    size: float
    fill_price: float
    sl_price: float
    tp_price: float
    reason: str = ""


class Broker(ABC):
    @abstractmethod
    def get_balance(self) -> float: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def place_order(
        self,
        asset: str,
        side: Literal["long", "short"],
        size_pct: float,
        mark_price: float,
        sl_price: float,
        tp_price: float,
    ) -> OrderResult: ...

    @abstractmethod
    def close_position(self, asset: str, mark_price: float) -> bool: ...

    @abstractmethod
    def mark_price(self, asset: str) -> float: ...

    def get_equity(self) -> float:
        """Total account value (cash + capital in open positions).

        Defaults to cash balance; brokers that hold positions should override.
        """
        return self.get_balance()
