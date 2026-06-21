from __future__ import annotations

import json
import logging
from pathlib import Path

from app.agents.base import AgentView, BaseAgent
from app.data.context import MarketContext
from app.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parent.parent.parent / "prompts" / "forecast.md").read_text()


class ForecastAgent(BaseAgent):
    name = "forecast"

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def analyze(self, ctx: MarketContext) -> AgentView:
        fc = ctx.forecast
        if not fc or fc.get("degraded"):
            return AgentView(
                agent=self.name,
                asset=ctx.asset,
                signal="neutral",
                confidence=0.0,
                rationale="forecast degraded or unavailable",
                extra={"degraded": True},
            )
        user_msg = json.dumps({
            "asset": ctx.asset,
            "timeframe": ctx.timeframe,
            "expected_move_pct": fc.get("expected_move_pct"),
            "direction": fc.get("direction"),
            "model_confidence": fc.get("confidence"),
            "mae": fc.get("mae"),
            "degraded": fc.get("degraded", False),
        })
        try:
            resp = self.gateway.complete(_PROMPT, user_msg)
            d = resp.parsed
            return AgentView(
                agent=self.name,
                asset=ctx.asset,
                signal=d.get("signal", "neutral"),
                confidence=float(d.get("confidence", 0.3)),
                rationale=d.get("rationale", ""),
                extra={
                    "expected_move_pct": d.get("expected_move_pct", fc.get("expected_move_pct")),
                    "uncertainty": d.get("uncertainty", "high"),
                },
            )
        except Exception as exc:
            logger.warning("ForecastAgent failed: %s", exc)
            return AgentView(agent=self.name, asset=ctx.asset, signal="neutral", confidence=0.0,
                             rationale=f"agent error: {exc}")
