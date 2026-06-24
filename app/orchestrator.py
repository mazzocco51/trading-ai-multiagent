from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agents.agent_selector import get_agents_for_asset_class, get_weights_for_asset_class
from app.agents.base import AgentView
from app.agents.forecast_agent import ForecastAgent
from app.agents.news_agent import NewsAgent
from app.agents.onchain import OnChainAgent
from app.agents.portfolio_manager import PortfolioManagerAgent, TradeIdea
from app.agents.risk_manager import RiskManager
from app.agents.sentiment_agent import SentimentAgent
from app.agents.technical import TechnicalAgent
from app.broker.base import Broker
from app.config import Settings
from app.data.asset_registry import AssetRegistry
from app.data.context import build_context
from app.data.stocks import get_stock_ohlcv, is_market_open
from app.explain import explain_cycle
from app.persistence.repo import save_decision, save_equity_snapshot

logger = logging.getLogger(__name__)

_AGENT_CLASS_MAP: dict[str, type] = {
    "technical": TechnicalAgent,
    "forecast": ForecastAgent,
    "sentiment": SentimentAgent,
    "onchain": OnChainAgent,
    "news": NewsAgent,
}


def run_cycle(
    settings: Settings,
    broker: Broker,
    gateway: Any,
    repo_session: Session,
) -> list[dict]:
    """Execute one full trading cycle across all configured assets.

    Returns a list of result dicts — one per asset — with keys:
    ``asset``, ``action``, ``veto``, ``veto_reason``, ``balance``.
    """
    equity_start_of_day = broker.get_equity()
    results: list[dict] = []
    registry = AssetRegistry(settings)

    for asset in settings.assets:
        logger.info("Processing asset: %s", asset)

        asset_class = registry.get_asset_class(asset)

        # ------------------------------------------------------------------ #
        # 0. Stock market-hours gate: skip when US equities are closed
        # ------------------------------------------------------------------ #
        if asset_class == "stock" and not is_market_open():
            logger.info("Market closed — skipping stock %s", asset)
            results.append(
                {
                    "asset": asset,
                    "action": "hold",
                    "veto": True,
                    "veto_reason": "US equity market is closed",
                    "balance": broker.get_balance(),
                }
            )
            continue

        # ------------------------------------------------------------------ #
        # 1. Build market context (route OHLCV source by asset class)
        # ------------------------------------------------------------------ #
        ohlcv_fn = get_stock_ohlcv if asset_class == "stock" else None
        try:
            ctx = build_context(
                asset, settings.timeframe, settings.whale_alert_api_key, ohlcv_fn=ohlcv_fn
            )
        except Exception as exc:
            logger.error("build_context failed for %s: %s", asset, exc)
            results.append(
                {
                    "asset": asset,
                    "action": "hold",
                    "veto": True,
                    "veto_reason": f"context build failed: {exc}",
                    "balance": broker.get_balance(),
                }
            )
            continue

        # ------------------------------------------------------------------ #
        # 2. Run specialist agents filtered by asset class
        # ------------------------------------------------------------------ #
        applicable_agent_names = get_agents_for_asset_class(asset_class)
        specialist_classes = [
            _AGENT_CLASS_MAP[n] for n in applicable_agent_names if n in _AGENT_CLASS_MAP
        ]
        asset_weights = get_weights_for_asset_class(settings.agent_weights, asset_class)

        views: list[AgentView] = []
        for AgentCls in specialist_classes:
            try:
                agent = AgentCls(gateway)  # type: ignore[call-arg]
                view = agent.analyze(ctx)
                views.append(view)
            except Exception as exc:
                logger.warning(
                    "Agent %s failed for %s: %s", AgentCls.__name__, asset, exc
                )

        # ------------------------------------------------------------------ #
        # 3. Derive mark price first (needed for position context)
        # ------------------------------------------------------------------ #
        mark_price: float
        if ctx.ohlcv:
            mark_price = float(ctx.ohlcv[-1].get("close", 0.0))
        else:
            mark_price = broker.mark_price(asset)

        # Current open position on this asset, passed to the manager so it can
        # decide to take profit / close on a consensus flip (not only via SL/TP).
        held = next((p for p in broker.get_positions() if p.asset == asset), None)
        open_position: dict | None = None
        force_close = False
        if held is not None:
            upnl = None
            age_hours = 0.0
            if mark_price > 0 and held.entry_price:
                direction = 1.0 if held.side == "long" else -1.0
                upnl = round((mark_price / held.entry_price - 1.0) * 100 * direction, 2)
            try:
                opened_dt = datetime.fromisoformat(held.opened_at.replace("Z", "+00:00"))
                age_hours = (datetime.now(UTC) - opened_dt).total_seconds() / 3600
                if mark_price > 0 and age_hours >= settings.max_holding_hours:
                    force_close = True
                    logger.info(
                        "Time-exit: %s held %.1fh >= %dh limit — forcing close",
                        asset, age_hours, settings.max_holding_hours,
                    )
            except Exception as exc:
                logger.debug("Could not parse opened_at for %s: %s", asset, exc)
            open_position = {
                "side": held.side,
                "entry_price": held.entry_price,
                "unrealized_pct": upnl,
                "opened_hours": round(age_hours, 1),
            }

        # ------------------------------------------------------------------ #
        # 4. Portfolio Manager aggregates views into a TradeIdea
        # ------------------------------------------------------------------ #
        pm = PortfolioManagerAgent(gateway, asset_weights)
        idea = pm.aggregate(views, asset, ctx, open_position=open_position)

        # ------------------------------------------------------------------ #
        # 5. Risk Manager validates / vetos the order
        # ------------------------------------------------------------------ #
        rm = RiskManager(settings)

        if force_close:
            idea = TradeIdea(
                asset=asset,
                action="close",
                target_size_pct=0.0,
                conviction=1.0,
                combined_rationale=(
                    f"Time-based exit: held {open_position['opened_hours']:.1f}h"
                    f" >= {settings.max_holding_hours}h limit"
                ),
                agent_views_summary=[],
            )

        order = rm.evaluate(idea, broker, mark_price, equity_start_of_day)

        # ------------------------------------------------------------------ #
        # 6. Execute — ONLY with a valid price. A missing/zero price must never
        #    open or (worse) close a position, or it books a fake P&L.
        # ------------------------------------------------------------------ #
        if mark_price <= 0:
            logger.warning(
                "Invalid price (%.4f) for %s — skipping execution this cycle", mark_price, asset
            )
        else:
            if not order.veto:
                if order.action in ("open_long", "open_short"):
                    side = "long" if order.action == "open_long" else "short"
                    if held is not None and held.side == side:
                        logger.info("Already holding %s %s — no stacking", side, asset)
                    else:
                        try:
                            broker.place_order(
                                asset,
                                side,  # type: ignore[arg-type]
                                order.size_pct,
                                mark_price,
                                order.sl_price,
                                order.tp_price,
                            )
                            logger.info(
                                "Placed %s order for %s size_pct=%.4f mark=%.4f",
                                side,
                                asset,
                                order.size_pct,
                                mark_price,
                            )
                        except Exception as exc:
                            logger.error("place_order failed for %s: %s", asset, exc)

                elif order.action == "close":
                    positions = {p.asset: p for p in broker.get_positions()}
                    if asset in positions:
                        try:
                            broker.close_position(asset, mark_price)
                            logger.info("Closed position for %s at %.4f", asset, mark_price)
                        except Exception as exc:
                            logger.error("close_position failed for %s: %s", asset, exc)

            # Check SL/TP for any existing position (broker-side guard)
            if hasattr(broker, "check_sl_tp"):
                try:
                    triggered = broker.check_sl_tp(asset, mark_price)
                    if triggered:
                        logger.info("SL/TP triggered for %s: %s", asset, triggered)
                except Exception as exc:
                    logger.warning("check_sl_tp failed for %s: %s", asset, exc)

        # ------------------------------------------------------------------ #
        # 6b. Human-readable, plain-Italian explanation of what just happened
        # ------------------------------------------------------------------ #
        try:
            print(explain_cycle(asset, mark_price, views, idea, order, broker.get_balance()))
        except Exception as exc:
            logger.warning("explain_cycle failed for %s: %s", asset, exc)

        # ------------------------------------------------------------------ #
        # 7. Persist decision and equity snapshot
        # ------------------------------------------------------------------ #
        try:
            save_decision(
                repo_session,
                asset=asset,
                action=order.action,
                conviction=idea.conviction,
                rationale=idea.combined_rationale,
                veto=order.veto,
                veto_reason=order.veto_reason,
                views=views,
            )
        except Exception as exc:
            logger.error("save_decision failed for %s: %s", asset, exc)

        try:
            save_equity_snapshot(repo_session, broker.get_balance())
        except Exception as exc:
            logger.error("save_equity_snapshot failed for %s: %s", asset, exc)

        results.append(
            {
                "asset": asset,
                "action": order.action,
                "veto": order.veto,
                "veto_reason": order.veto_reason,
                "balance": broker.get_balance(),
            }
        )

    return results
