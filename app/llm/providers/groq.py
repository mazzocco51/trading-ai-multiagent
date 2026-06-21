from __future__ import annotations

import json

import httpx

from app.llm.providers.base import BaseLLMProvider, LLMResponse


class GroqProvider(BaseLLMProvider):
    name = "groq"

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile") -> None:
        self.api_key = api_key
        self.model = model

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, user: str) -> LLMResponse:
        resp = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        tokens_used = data.get("usage", {}).get("total_tokens", 0)
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {}
        return LLMResponse(
            provider=self.name,
            model=self.model,
            content=content,
            parsed=parsed,
            tokens_used=tokens_used,
        )
