from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.agents.base import AgentView
from app.agents.forecast_agent import ForecastAgent
from app.agents.news_agent import NewsAgent
from app.agents.onchain import OnChainAgent
from app.agents.portfolio_manager import PortfolioManagerAgent
from app.agents.risk_manager import RiskManager
from app.agents.sentiment_agent import SentimentAgent
from app.agents.technical import TechnicalAgent
from app.broker.base import Broker
from app.config import Settings
from app.data.context import build_context
from app.explain import explain_cycle
from app.persistence.repo import save_decision, save_equity_snapshot

logger = logging.getLogger(__name__)


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
    equity_start_of_day = broker.get_balance()
    results: list[dict] = []

    for asset in settings.assets:
        logger.info("Processing asset: %s", asset)

        # ------------------------------------------------------------------ #
        # 1. Build market context
        # ------------------------------------------------------------------ #
        try:
            ctx = build_context(asset, settings.timeframe, settings.whale_alert_api_key)
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
        # 2. Run specialist agents (failures are non-fatal)
        # ------------------------------------------------------------------ #
        specialist_classes = [
            TechnicalAgent,
            ForecastAgent,
            SentimentAgent,
            OnChainAgent,
            NewsAgent,
        ]

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
        # 3. Portfolio Manager aggregates views into a TradeIdea
        # ------------------------------------------------------------------ #
        pm = PortfolioManagerAgent(gateway, settings.agent_weights)
        idea = pm.aggregate(views, asset, ctx)

        # ------------------------------------------------------------------ #
        # 4. Derive mark price from context (fallback to broker)
        # ------------------------------------------------------------------ #
        mark_price: float
        if ctx.ohlcv:
            mark_price = float(ctx.ohlcv[-1].get("close", 0.0))
        else:
            mark_price = broker.mark_price(asset)

        # ------------------------------------------------------------------ #
        # 5. Risk Manager validates / vetos the order
        # ------------------------------------------------------------------ #
        rm = RiskManager(settings)
        order = rm.evaluate(idea, broker, mark_price, equity_start_of_day)

        # ------------------------------------------------------------------ #
        # 6. Execute
        # ------------------------------------------------------------------ #
        if not order.veto:
            if order.action in ("open_long", "open_short"):
                side = "long" if order.action == "open_long" else "short"
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
