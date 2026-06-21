from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.agents.base import AgentView, BaseAgent
from app.data.context import MarketContext
from app.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "portfolio_manager.md"


class TradeIdea(BaseModel):
    asset: str
    action: Literal["open_long", "open_short", "close", "hold"]
    target_size_pct: float  # 0..1
    conviction: float       # 0..1
    combined_rationale: str
    agent_views_summary: list[dict] = []


class PortfolioManagerAgent(BaseAgent):
    name = "portfolio_manager"

    def __init__(self, gateway: LLMGateway, weights: dict[str, float]) -> None:
        self.gateway = gateway
        self.weights = weights

    def analyze(self, ctx: MarketContext) -> AgentView:
        raise NotImplementedError("Use aggregate(views, asset, ctx) instead")

    def aggregate(self, views: list[AgentView], asset: str, ctx: MarketContext) -> TradeIdea:
        signal_map = {"long": 1.0, "short": -1.0, "neutral": 0.0}
        weighted_score = 0.0
        total_weight = 0.0
        views_summary: list[dict] = []

        for v in views:
            w = self.weights.get(v.agent, 0.1)
            score = signal_map.get(v.signal, 0.0) * v.confidence * w
            weighted_score += score
            total_weight += w
            views_summary.append({
                "agent": v.agent,
                "signal": v.signal,
                "confidence": v.confidence,
                "weight": w,
                "rationale": v.rationale[:200],
            })

        norm_score = weighted_score / (total_weight or 1.0)

        user_msg = json.dumps({
            "asset": asset,
            "timeframe": ctx.timeframe,
            "weighted_signal_score": round(norm_score, 4),
            "agent_views": views_summary,
            "current_indicators": ctx.indicators,
        })

        try:
            system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
            resp = self.gateway.complete(system=system_prompt, user=user_msg)
            raw = resp.content.strip()
            # Strip markdown fences if the model added them despite instructions
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            action: str = data["action"]
            if action not in {"open_long", "open_short", "close", "hold"}:
                raise ValueError(f"Invalid action: {action!r}")
            size_pct = max(0.0, min(0.25, float(data["target_size_pct"])))
            conviction = max(0.0, min(1.0, float(data["conviction"])))
            return TradeIdea(
                asset=asset,
                action=action,  # type: ignore[arg-type]
                target_size_pct=size_pct,
                conviction=conviction,
                combined_rationale=str(data.get("combined_rationale", "")),
                agent_views_summary=views_summary,
            )
        except Exception as exc:
            logger.warning("PortfolioManager LLM call failed (%s); using rule-based fallback", exc)

        # Rule-based fallback
        if norm_score > 0.2:
            fb_action: Literal["open_long", "open_short", "close", "hold"] = "open_long"
        elif norm_score < -0.2:
            fb_action = "open_short"
        else:
            fb_action = "hold"

        fb_size = min(abs(norm_score) * 0.25, 0.20)
        fb_conviction = abs(norm_score)

        return TradeIdea(
            asset=asset,
            action=fb_action,
            target_size_pct=fb_size,
            conviction=fb_conviction,
            combined_rationale=f"Fallback rule applied. Weighted score: {norm_score:.4f}",
            agent_views_summary=views_summary,
        )
