from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class LLMResponse(BaseModel):
    provider: str
    model: str
    content: str
    parsed: dict
    tokens_used: int = 0


class BaseLLMProvider(ABC):
    name: str

    @abstractmethod
    def complete(self, system: str, user: str) -> LLMResponse: ...

    @abstractmethod
    def is_available(self) -> bool: ...
