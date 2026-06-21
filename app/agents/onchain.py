from __future__ import annotations

import json
import logging
from pathlib import Path

from app.agents.base import AgentView, BaseAgent
from app.data.context import MarketContext
from app.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parent.parent.parent / "prompts" / "onchain.md").read_text()


class OnChainAgent(BaseAgent):
    name = "onchain"

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def analyze(self, ctx: MarketContext) -> AgentView:
        events = ctx.whale_events
        if not events:
            return AgentView(
                agent=self.name,
                asset=ctx.asset,
                signal="neutral",
                confidence=0.1,
                rationale="no whale events detected",
                extra={"pressure": "neutral", "notable_events": []},
            )
        user_msg = json.dumps({
            "asset": ctx.asset,
            "whale_events": events[:20],  # cap to avoid token overflow
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
                    "pressure": d.get("pressure", "neutral"),
                    "notable_events": d.get("notable_events", []),
                },
            )
        except Exception as exc:
            logger.warning("OnChainAgent failed: %s", exc)
            return AgentView(agent=self.name, asset=ctx.asset, signal="neutral", confidence=0.0,
                             rationale=f"agent error: {exc}")
