from __future__ import annotations

import json
import logging
from pathlib import Path

from app.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)
_PROMPT_PATH = Path(__file__).parent.parent.parent / "prompts" / "reflection.md"


class ReflectionAgent:
    name = "reflection"

    def __init__(self, gateway: LLMGateway) -> None:
        self.gateway = gateway

    def reflect(self, recent_trades: list[dict], current_lessons: list[str]) -> list[str]:
        """Return 3-6 short concrete rules distilled from trade history.

        recent_trades: list of dicts with keys asset, side, entry_price, exit_price,
                       pnl, opened_at, closed_at (from trade_history).
        current_lessons: existing lessons to avoid repeating.
        Returns a list of lesson strings (3-6 items).
        """
        user_msg = json.dumps({
            "recent_trades": recent_trades,
            "existing_lessons": current_lessons,
        })
        try:
            system_prompt = _PROMPT_PATH.read_text(encoding="utf-8")
            resp = self.gateway.complete(system=system_prompt, user=user_msg)
            raw = resp.content.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)
            lessons = data.get("lessons", [])
            if not isinstance(lessons, list):
                raise ValueError("lessons must be a list")
            return [str(le) for le in lessons[:6]]
        except Exception as exc:
            logger.warning("ReflectionAgent failed: %s", exc)
            return []
