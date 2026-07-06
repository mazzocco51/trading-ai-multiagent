"""Bull vs Bear debate step (TradingAgents-style), run before PM aggregation.

Live mode: an LLM BULL agent argues the long thesis and an LLM BEAR agent the
short thesis over 1-2 rounds; the PortfolioManager then acts as judge, seeing
the transcript alongside the existing weighted vote.

Deterministic backtest mode: the debate cannot "argue", so a proxy penalises
the final conviction when bull and bear evidence are BOTH strong (high
disagreement / signal dispersion between agents) and leaves it unchanged when
the evidence is one-sided.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.agents.base import AgentView
from app.data.context import MarketContext

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"
_DEBATE_PROMPT = _PROMPTS_DIR / "debate.md"

_MAX_ARGUMENT_CHARS = 900


class DebateTurn(BaseModel):
    role: Literal["bull", "bear"]
    round: int
    argument: str


class DebateTranscript(BaseModel):
    asset: str
    turns: list[DebateTurn] = []
    bull_summary: str = ""
    bear_summary: str = ""

    def as_dicts(self) -> list[dict]:
        return [t.model_dump() for t in self.turns]


class DebateAgent:
    """Runs the bull/bear LLM debate and returns the transcript.

    Both sides argue in ONE combined LLM call per round (instead of two
    separate calls) to stay within free-tier rate limits.
    """

    name = "debate"

    def __init__(self, gateway, rounds: int = 1) -> None:
        self.gateway = gateway
        self.rounds = max(1, min(2, rounds))

    def run(self, views: list[AgentView], ctx: MarketContext) -> DebateTranscript:
        transcript = DebateTranscript(asset=ctx.asset)
        views_payload = [
            {
                "agent": v.agent,
                "signal": v.signal,
                "confidence": v.confidence,
                "rationale": v.rationale[:200],
            }
            for v in views
        ]
        for rnd in range(1, self.rounds + 1):
            user_msg = json.dumps({
                "asset": ctx.asset,
                "timeframe": ctx.timeframe,
                "round": rnd,
                "agent_views": views_payload,
                "indicators": ctx.indicators,
                "debate_so_far": transcript.as_dicts(),
            })
            try:
                system_prompt = _DEBATE_PROMPT.read_text(encoding="utf-8")
                resp = self.gateway.complete(system=system_prompt, user=user_msg)
                bull_arg, bear_arg = _extract_sides(resp.content, resp.parsed)
            except Exception as exc:
                logger.warning("Debate round %d failed: %s", rnd, exc)
                continue
            for role, argument in (("bull", bull_arg), ("bear", bear_arg)):
                if not argument:
                    continue
                transcript.turns.append(
                    DebateTurn(role=role, round=rnd, argument=argument)  # type: ignore[arg-type]
                )
        # Summaries = last argument per side (the most refined one)
        for turn in transcript.turns:
            if turn.role == "bull":
                transcript.bull_summary = turn.argument
            else:
                transcript.bear_summary = turn.argument
        return transcript


def _extract_argument(raw: str) -> str:
    """Accept either plain text or a JSON object with an "argument" key."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
            text = str(data.get("argument", text))
        except Exception:
            pass
    return text[:_MAX_ARGUMENT_CHARS]


def _extract_sides(raw: str, parsed: dict | None = None) -> tuple[str, str]:
    """Pull ("bull", "bear") arguments from a combined debate response."""
    data: dict = parsed if isinstance(parsed, dict) and parsed else {}
    if not data:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            loaded = json.loads(text)
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    bull = str(data.get("bull") or data.get("bull_argument") or "").strip()
    bear = str(data.get("bear") or data.get("bear_argument") or "").strip()
    return bull[:_MAX_ARGUMENT_CHARS], bear[:_MAX_ARGUMENT_CHARS]


# ---------------------------------------------------------------------------
# Borderline gate — run the LLM debate only when the call is genuinely close
# ---------------------------------------------------------------------------


def weighted_signal_score(views: list[AgentView], weights: dict[str, float]) -> float:
    """Same normalised score the PortfolioManager computes before judging."""
    signal_map = {"long": 1.0, "short": -1.0, "neutral": 0.0}
    weighted = 0.0
    total_weight = 0.0
    active_weight = 0.0
    for v in views:
        w = weights.get(v.agent, 0.1)
        weighted += signal_map.get(v.signal, 0.0) * v.confidence * w
        total_weight += w
        if v.confidence > 0:
            active_weight += w
    return weighted / (active_weight or total_weight or 1.0)


def is_borderline(
    views: list[AgentView],
    weights: dict[str, float],
    low: float = 0.05,
    high: float = 0.35,
) -> bool:
    """True when |weighted score| falls in the borderline band [low, high] —
    i.e. the debate can actually swing the decision."""
    return low <= abs(weighted_signal_score(views, weights)) <= high


# ---------------------------------------------------------------------------
# Deterministic proxy (backtestable)
# ---------------------------------------------------------------------------


def debate_conviction_factor(
    views: list[AgentView],
    weights: dict[str, float],
    max_penalty: float = 0.5,
) -> float:
    """Multiplier in [1 - max_penalty, 1.0] for the final conviction.

    Bull strength = weighted confidence of long views; bear strength = same for
    short views. Disagreement = 2*min/(bull+bear): 0 when one-sided (factor
    stays 1.0 → behaviour unchanged), 1 when perfectly split (full penalty).
    """
    bull = sum(
        weights.get(v.agent, 0.1) * v.confidence for v in views if v.signal == "long"
    )
    bear = sum(
        weights.get(v.agent, 0.1) * v.confidence for v in views if v.signal == "short"
    )
    total = bull + bear
    if total <= 1e-12:
        return 1.0
    disagreement = 2.0 * min(bull, bear) / total  # 0..1
    return 1.0 - max_penalty * disagreement


def apply_debate_proxy(idea, views: list[AgentView], weights: dict[str, float],
                       max_penalty: float = 0.5):
    """Scale a TradeIdea's conviction/size by the deterministic debate factor.

    Open signals whose penalised conviction drops below 0.15 (the PM fallback's
    own close threshold) are downgraded to hold. One-sided inputs pass through
    unchanged (factor 1.0).
    """
    factor = debate_conviction_factor(views, weights, max_penalty=max_penalty)
    if factor >= 1.0:
        return idea
    new_conviction = idea.conviction * factor
    update: dict = {
        "conviction": new_conviction,
        "target_size_pct": idea.target_size_pct * factor,
        "combined_rationale": (
            idea.combined_rationale
            + f" [debate proxy: disagreement penalty x{factor:.2f}]"
        ),
    }
    if idea.action in ("open_long", "open_short") and new_conviction < 0.15:
        update["action"] = "hold"
        update["target_size_pct"] = 0.0
        update["combined_rationale"] += " — open downgraded to hold"
    return idea.model_copy(update=update)
