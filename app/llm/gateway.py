from __future__ import annotations

import logging
from datetime import date

from app.llm.providers.base import BaseLLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class LLMBudgetExceeded(Exception):
    pass


class LLMAllProvidersFailed(Exception):
    pass


class LLMGateway:
    def __init__(self, providers: list[BaseLLMProvider], daily_limit: int = 1400) -> None:
        self.providers = providers
        self.daily_limit = daily_limit
        self._request_count: int = 0
        self._reset_date: str = str(date.today())

    def _check_and_reset_date(self) -> None:
        today = str(date.today())
        if today != self._reset_date:
            self._request_count = 0
            self._reset_date = today

    def requests_today(self) -> int:
        self._check_and_reset_date()
        return self._request_count

    def complete(self, system: str, user: str) -> LLMResponse:
        self._check_and_reset_date()
        if self._request_count >= self.daily_limit:
            raise LLMBudgetExceeded(f"Daily limit of {self.daily_limit} requests reached")

        last_exc: Exception | None = None
        for provider in self.providers:
            if not provider.is_available():
                continue
            try:
                resp = provider.complete(system, user)
                self._request_count += 1
                logger.info("LLM response from %s (%d tokens)", provider.name, resp.tokens_used)
                return resp
            except Exception as exc:
                logger.warning("Provider %s failed: %s", provider.name, exc)
                last_exc = exc

        raise LLMAllProvidersFailed(f"All providers failed. Last error: {last_exc}")
