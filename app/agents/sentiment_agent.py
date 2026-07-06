from __future__ import annotations

import json
import logging
from pathlib import Path

from app.agents.base import AgentView, BaseAgent, degraded_rationale
from app.data.context import MarketContext
from app.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parent.parent.parent / "prompts" / "sentiment.md").read_text()


class SentimentAgent(BaseAgent):
    name = "sentiment"

    def __init__(
        self,
        gateway: LLMGateway,
        extreme_only: bool = False,
        extreme_threshold: int = 25,
    ) -> None:
        self.gateway = gateway
        self.extreme_only = extreme_only
        self.extreme_threshold = extreme_threshold

    def analyze(self, ctx: MarketContext) -> AgentView:
        fng = ctx.fear_and_greed
        if not fng or "degraded" in ctx.degraded_sources:
            return AgentView(
                agent=self.name,
                asset=ctx.asset,
                signal="neutral",
                confidence=0.0,
                rationale="fear & greed data unavailable",
            )

        # Only act on extreme Fear & Greed readings; stay neutral in mid-range.
        fng_value = fng.get("value")
        if self.extreme_only and fng_value is not None:
            val = int(fng_value)
            if self.extreme_threshold <= val <= (100 - self.extreme_threshold):
                return AgentView(
                    agent=self.name,
                    asset=ctx.asset,
                    signal="neutral",
                    confidence=0.0,
                    rationale="F&G not in extreme zone",
                )

        user_msg = json.dumps({
            "asset": ctx.asset,
            "fear_and_greed_value": fng.get("value"),
            "fear_and_greed_label": fng.get("label"),
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
                extra={
                    "regime": d.get("regime", "neutral"),
                    "contrarian": d.get("contrarian", False),
                },
            )
        except Exception as exc:
            logger.warning("SentimentAgent failed: %s", exc)
            return AgentView(agent=self.name, asset=ctx.asset, signal="neutral", confidence=0.0,
                             rationale=degraded_rationale(exc))

    def cache_key(self, ctx: MarketContext) -> str | None:
        # Fear & Greed is a global market signal — identical across assets.
        fng = ctx.fear_and_greed or {}
        degraded = "degraded" in ctx.degraded_sources
        return f"fng:{fng.get('value')}:{fng.get('label')}:{degraded}"
