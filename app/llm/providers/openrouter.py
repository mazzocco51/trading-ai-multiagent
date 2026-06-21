from __future__ import annotations

import json

import httpx

from app.llm.providers.base import BaseLLMProvider, LLMResponse


class OpenRouterProvider(BaseLLMProvider):
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str = "meta-llama/llama-3.3-70b-instruct:free",
    ) -> None:
        self.api_key = api_key
        self.model = model

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, user: str) -> LLMResponse:
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://github.com/trading-ai-multiagent",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
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
            provider=self.name, model=self.model, content=content, parsed=parsed, tokens_used=tokens_used
        )
