from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.agents.portfolio_manager import TradeIdea
from app.broker.base import Broker
from app.config import Settings


class ValidatedOrder(BaseModel):
    asset: str
    action: Literal["open_long", "open_short", "close", "hold"]
    size_pct: float
    sl_pct: float
    tp_pct: float
    mark_price: float
    sl_price: float
    tp_price: float
    veto: bool = False
    veto_reason: str = ""


class RiskManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(
        self,
        idea: TradeIdea,
        broker: Broker,
        mark_price: float,
        equity_start_of_day: float,
    ) -> ValidatedOrder:
        s = self.settings
        action = idea.action

        # hold/close always pass — build base order and return immediately
        if action in ("hold", "close"):
            return self._build_order(idea, action, 0.0, mark_price, veto=False)

        # --- Kill-switch: daily drawdown (measured on equity, not just cash) ---
        current_equity = broker.get_equity()
        if equity_start_of_day > 0:
            daily_drawdown = (equity_start_of_day - current_equity) / equity_start_of_day
            if daily_drawdown >= s.max_daily_drawdown_pct:
                return self._build_order(
                    idea, action, 0.0, mark_price,
                    veto=True,
                    veto_reason=(
                        f"Kill-switch: daily drawdown {daily_drawdown:.2%} >= "
                        f"{s.max_daily_drawdown_pct:.2%}"
                    ),
                )

        positions = broker.get_positions()

        # --- Max open positions ---
        if len(positions) >= s.max_open_positions:
            return self._build_order(
                idea, action, 0.0, mark_price,
                veto=True,
                veto_reason=(
                    f"Max open positions reached ({s.max_open_positions})"
                ),
            )

        # --- No flip: veto if opposite side already open for this asset ---
        desired_side = "long" if action == "open_long" else "short"
        for pos in positions:
            if pos.asset == idea.asset and pos.side != desired_side:
                return self._build_order(
                    idea, action, 0.0, mark_price,
                    veto=True,
                    veto_reason=(
                        f"Opposite position already open for {idea.asset} "
                        f"(side={pos.side}); close it first"
                    ),
                )

        # --- Size cap ---
        size_pct = min(idea.target_size_pct, s.max_position_pct)

        # --- Total exposure cap ---
        current_exposure = sum(pos.size_pct for pos in positions)
        if current_exposure + size_pct > s.max_total_exposure_pct:
            allowed = s.max_total_exposure_pct - current_exposure
            if allowed <= 0.0:
                return self._build_order(
                    idea, action, 0.0, mark_price,
                    veto=True,
                    veto_reason=(
                        f"Total exposure cap reached: current={current_exposure:.2%}, "
                        f"max={s.max_total_exposure_pct:.2%}"
                    ),
                )
            size_pct = min(size_pct, allowed)

        return self._build_order(idea, action, size_pct, mark_price, veto=False)

    # ------------------------------------------------------------------
    def _build_order(
        self,
        idea: TradeIdea,
        action: str,
        size_pct: float,
        mark_price: float,
        *,
        veto: bool,
        veto_reason: str = "",
    ) -> ValidatedOrder:
        s = self.settings
        sl_pct = s.default_sl_pct
        tp_pct = s.default_tp_pct

        if action == "open_long":
            sl_price = mark_price * (1.0 - sl_pct)
            tp_price = mark_price * (1.0 + tp_pct)
        elif action == "open_short":
            sl_price = mark_price * (1.0 + sl_pct)
            tp_price = mark_price * (1.0 - tp_pct)
        else:
            sl_price = mark_price
            tp_price = mark_price

        return ValidatedOrder(
            asset=idea.asset,
            action=action,  # type: ignore[arg-type]
            size_pct=size_pct,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            mark_price=mark_price,
            sl_price=sl_price,
            tp_price=tp_price,
            veto=veto,
            veto_reason=veto_reason,
        )
