from __future__ import annotations

import json

import httpx

from app.llm.providers.base import BaseLLMProvider, LLMResponse


class GeminiProvider(BaseLLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        self.api_key = api_key
        self.model = model

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, user: str) -> LLMResponse:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        body = {
            "contents": [{"parts": [{"text": system + "\n\n" + user}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }
        resp = httpx.post(url, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {}
        return LLMResponse(provider=self.name, model=self.model, content=content, parsed=parsed)
