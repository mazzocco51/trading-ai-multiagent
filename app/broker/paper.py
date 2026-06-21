from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from app.broker.base import Broker, OrderResult, Position


class PaperBroker(Broker):
    def __init__(
        self,
        initial_balance: float = 10_000.0,
        fee_pct: float = 0.001,
        slippage_pct: float = 0.0005,
    ) -> None:
        self._balance = initial_balance
        self.fee_pct = fee_pct
        self.slippage_pct = slippage_pct
        self.positions: dict[str, Position] = {}
        self.trade_history: list[dict] = []
        self._mock_prices: dict[str, float] = {}

    def set_mock_price(self, asset: str, price: float) -> None:
        self._mock_prices[asset] = price

    def get_balance(self) -> float:
        return self._balance

    def get_positions(self) -> list[Position]:
        return list(self.positions.values())

    def mark_price(self, asset: str) -> float:
        return self._mock_prices.get(asset, 0.0)

    def place_order(
        self,
        asset: str,
        side: Literal["long", "short"],
        size_pct: float,
        mark_price: float,
        sl_price: float,
        tp_price: float,
    ) -> OrderResult:
        if side == "long":
            fill_price = mark_price * (1 + self.slippage_pct)
        else:
            fill_price = mark_price * (1 - self.slippage_pct)

        size_units = (self._balance * size_pct) / fill_price
        cost = size_units * fill_price
        fee = cost * self.fee_pct
        total_cost = cost + fee

        if total_cost > self._balance:
            return OrderResult(
                success=False,
                order_id="",
                asset=asset,
                side=side,
                size=0.0,
                fill_price=fill_price,
                sl_price=sl_price,
                tp_price=tp_price,
                reason="insufficient_balance",
            )

        self._balance -= total_cost
        order_id = str(uuid.uuid4())
        self.positions[asset] = Position(
            asset=asset,
            side=side,
            size=size_units,
            entry_price=fill_price,
            sl_price=sl_price,
            tp_price=tp_price,
            opened_at=datetime.now(tz=UTC).isoformat(),
            size_pct=size_pct,
        )
        return OrderResult(
            success=True,
            order_id=order_id,
            asset=asset,
            side=side,
            size=size_units,
            fill_price=fill_price,
            sl_price=sl_price,
            tp_price=tp_price,
        )

    def close_position(self, asset: str, mark_price: float) -> bool:
        pos = self.positions.pop(asset, None)
        if pos is None:
            return False

        fee = pos.size * mark_price * self.fee_pct
        proceeds = pos.size * mark_price - fee

        if pos.side == "long":
            pnl = (mark_price - pos.entry_price) * pos.size - fee
        else:
            pnl = (pos.entry_price - mark_price) * pos.size - fee

        self._balance += proceeds
        self.trade_history.append(
            {
                "asset": asset,
                "side": pos.side,
                "entry_price": pos.entry_price,
                "exit_price": mark_price,
                "size": pos.size,
                "pnl": pnl,
                "closed_at": datetime.now(tz=UTC).isoformat(),
            }
        )
        return True

    def check_sl_tp(self, asset: str, current_price: float) -> str | None:
        pos = self.positions.get(asset)
        if pos is None:
            return None

        if pos.side == "long":
            if current_price <= pos.sl_price:
                self.close_position(asset, current_price)
                return "sl"
            if current_price >= pos.tp_price:
                self.close_position(asset, current_price)
                return "tp"
        else:
            if current_price >= pos.sl_price:
                self.close_position(asset, current_price)
                return "sl"
            if current_price <= pos.tp_price:
                self.close_position(asset, current_price)
                return "tp"

        return None
