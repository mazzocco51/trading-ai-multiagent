from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from app.agents.base import AgentView, BaseAgent, degraded_rationale
from app.data.context import MarketContext
from app.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).parent.parent.parent / "prompts" / "news.md").read_text()


class NewsAgent(BaseAgent):
    name = "news"

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def analyze(self, ctx: MarketContext) -> AgentView:
        headlines = ctx.news_headlines
        if not headlines:
            return AgentView(
                agent=self.name,
                asset=ctx.asset,
                signal="neutral",
                confidence=0.1,
                rationale="no recent news available",
                extra={"headline_risk": "low"},
            )
        user_msg = json.dumps({
            "asset": ctx.asset,
            "headlines": headlines[:15],  # cap to avoid token overflow
        })
        try:
            resp = self.gateway.complete(_PROMPT, user_msg)
            d = resp.parsed
            return AgentView(
                agent=self.name,
                asset=ctx.asset,
                signal=d.get("signal", "neutral"),
                confidence=float(d.get("confidence", 0.4)),
                rationale=d.get("rationale", ""),
                extra={
                    "headline_risk": d.get("headline_risk", "low"),
                    "summary": d.get("summary", ""),
                },
            )
        except Exception as exc:
            logger.warning("NewsAgent failed: %s", exc)
            return AgentView(agent=self.name, asset=ctx.asset, signal="neutral", confidence=0.0,
                             rationale=degraded_rationale(exc))

    def cache_key(self, ctx: MarketContext) -> str | None:
        # The news feed is often shared between assets; same headlines → same view.
        payload = json.dumps(ctx.news_headlines[:15], sort_keys=True, default=str)
        return "news:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
