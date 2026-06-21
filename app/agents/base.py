from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, field_validator

if TYPE_CHECKING:
    from app.data.context import MarketContext


class AgentView(BaseModel):
    agent: str
    asset: str
    signal: str  # long | short | neutral
    confidence: float  # 0..1
    rationale: str
    extra: dict[str, Any] = {}

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("signal", mode="before")
    @classmethod
    def validate_signal(cls, v: object) -> str:
        # Map common LLM phrasings to the canonical labels.
        synonyms = {
            "bullish": "long", "buy": "long", "up": "long", "positive": "long",
            "bearish": "short", "sell": "short", "down": "short", "negative": "short",
            "hold": "neutral", "flat": "neutral", "none": "neutral", "mixed": "neutral",
        }
        s = str(v).strip().lower()
        s = synonyms.get(s, s)
        allowed = {"long", "short", "neutral"}
        if s not in allowed:
            raise ValueError(f"signal must be one of {allowed}, got {v!r}")
        return s


class BaseAgent(ABC):
    name: str = "base"

    @abstractmethod
    def analyze(self, ctx: MarketContext) -> AgentView: ...
