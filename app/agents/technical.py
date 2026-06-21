from __future__ import annotations

import json
import logging
from pathlib import Path

from app.agents.base import AgentView, BaseAgent
from app.data.context import MarketContext
from app.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parent.parent.parent / "prompts" / "technical.md").read_text()


class TechnicalAgent(BaseAgent):
    name = "technical"

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def analyze(self, ctx: MarketContext) -> AgentView:
        ind = ctx.indicators
        user_msg = json.dumps({
            "asset": ctx.asset,
            "timeframe": ctx.timeframe,
            "macd": ind.get("macd"),
            "macd_signal": ind.get("macd_signal"),
            "macd_hist": ind.get("macd_hist"),
            "rsi": ind.get("rsi"),
            "pivot": ind.get("pivot"),
            "r1": ind.get("r1"),
            "s1": ind.get("s1"),
            "r2": ind.get("r2"),
            "s2": ind.get("s2"),
            "last_close": ctx.ohlcv[-1].get("close") if ctx.ohlcv else None,
        })
        try:
            resp = self.gateway.complete(_PROMPT, user_msg)
            d = resp.parsed
            return AgentView(
                agent=self.name,
                asset=ctx.asset,
                signal=d.get("signal", "neutral"),
                confidence=float(d.get("confidence", 0.5)),
                rationale=d.get("rationale", ""),
                extra={"key_levels": d.get("key_levels", {})},
            )
        except Exception as exc:
            logger.warning("TechnicalAgent failed: %s", exc)
            return AgentView(agent=self.name, asset=ctx.asset, signal="neutral", confidence=0.0,
                             rationale=f"agent error: {exc}")
