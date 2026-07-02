from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

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

    def aggregate(
        self,
        views: list[AgentView],
        asset: str,
        ctx: MarketContext,
        open_position: dict | None = None,
        lessons: list[str] | None = None,
        debate: Any | None = None,
    ) -> TradeIdea:
        signal_map = {"long": 1.0, "short": -1.0, "neutral": 0.0}
        weighted_score = 0.0
        total_weight = 0.0
        active_weight = 0.0  # weight of agents that actually produced a signal
        views_summary: list[dict] = []

        for v in views:
            w = self.weights.get(v.agent, 0.1)
            has_signal = v.confidence > 0
            score = signal_map.get(v.signal, 0.0) * v.confidence * w
            weighted_score += score
            total_weight += w
            if has_signal:
                active_weight += w
            views_summary.append({
                "agent": v.agent,
                "signal": v.signal,
                "confidence": v.confidence,
                "weight": w,
                "active": has_signal,
                "rationale": v.rationale[:200],
            })

        # Normalise by active weight so missing agents don't dilute conviction
        norm_score = weighted_score / (active_weight or total_weight or 1.0)

        # Floor: single weak source → cap conviction to avoid acting on thin data
        low_coverage = active_weight < 0.30
        if low_coverage:
            norm_score = max(-0.30, min(0.30, norm_score))

        user_msg = json.dumps({
            "asset": asset,
            "timeframe": ctx.timeframe,
            "weighted_signal_score": round(norm_score, 4),
            "active_weight_sum": round(active_weight, 4),
            "low_coverage": low_coverage,
            "agent_views": views_summary,
            "current_indicators": ctx.indicators,
            "current_position": open_position,  # {"side","entry_price","unrealized_pct"} or null
            "lessons_learned": lessons or [],
            # Bull-vs-bear debate transcript (null when the debate feature is off)
            "debate_transcript": debate.as_dicts() if debate is not None else None,
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

        # Rule-based fallback (position-aware)
        held = (open_position or {}).get("side")
        fb_action: Literal["open_long", "open_short", "close", "hold"]
        if held == "long":
            fb_action = "close" if norm_score < -0.10 else "hold"
        elif held == "short":
            fb_action = "close" if norm_score > 0.10 else "hold"
        elif norm_score > 0.15:
            fb_action = "open_long"
        elif norm_score < -0.15:
            fb_action = "open_short"
        else:
            fb_action = "hold"

        fb_size = min(abs(norm_score) * 0.25, 0.20)
        fb_conviction = abs(norm_score)

        coverage_note = (
            f" [low coverage: active_weight={active_weight:.2f}]" if low_coverage else ""
        )
        rationale = f"Fallback rule applied. Weighted score: {norm_score:.4f}{coverage_note}"
        return TradeIdea(
            asset=asset,
            action=fb_action,
            target_size_pct=fb_size,
            conviction=fb_conviction,
            combined_rationale=rationale,
            agent_views_summary=views_summary,
        )
