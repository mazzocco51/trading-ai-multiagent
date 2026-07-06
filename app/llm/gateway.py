from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from datetime import date

import httpx

from app.llm.providers.base import BaseLLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class LLMBudgetExceeded(Exception):
    pass


class LLMAllProvidersFailed(Exception):
    pass


class LLMRateLimited(LLMAllProvidersFailed):
    """Every provider is rate-limited (429) and retries are exhausted."""


def _is_rate_limit(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429
    return "429" in str(exc)


def _retry_after_seconds(exc: Exception, default: float) -> float:
    """Cooldown from the Retry-After header when present, else ``default``."""
    if isinstance(exc, httpx.HTTPStatusError):
        raw = exc.response.headers.get("Retry-After")
        if raw:
            try:
                return max(1.0, float(raw))
            except ValueError:
                pass  # HTTP-date variant — fall back to the default
    return default


class LLMGateway:
    def __init__(
        self,
        providers: list[BaseLLMProvider],
        daily_limit: int = 1400,
        rpm: dict[str, float] | None = None,
        max_retries: int = 3,
        cooldown_seconds: float = 60.0,
        max_backoff_wait: float = 120.0,
        sleep_fn: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.providers = providers
        self.daily_limit = daily_limit
        self.rpm = rpm or {}
        self.max_retries = max_retries
        self.cooldown_seconds = cooldown_seconds
        self.max_backoff_wait = max_backoff_wait
        self._sleep = sleep_fn
        self._clock = clock
        self._request_count: int = 0
        self._reset_date: str = str(date.today())
        self._cooldown_until: dict[str, float] = {}
        self._last_call_at: dict[str, float] = {}

    def _check_and_reset_date(self) -> None:
        today = str(date.today())
        if today != self._reset_date:
            self._request_count = 0
            self._reset_date = today

    def requests_today(self) -> int:
        self._check_and_reset_date()
        return self._request_count

    # ------------------------------------------------------------------ #
    # Rate limiting internals
    # ------------------------------------------------------------------ #

    def _min_interval(self, name: str) -> float:
        rpm = self.rpm.get(name, 0)
        return 60.0 / rpm if rpm and rpm > 0 else 0.0

    def _in_cooldown(self, name: str) -> bool:
        return self._cooldown_until.get(name, 0.0) > self._clock()

    def _pace(self, name: str) -> None:
        """Enforce the per-provider minimum interval between calls."""
        interval = self._min_interval(name)
        if interval <= 0:
            return
        last = self._last_call_at.get(name)
        if last is None:
            return
        wait = interval - (self._clock() - last)
        if wait > 0:
            logger.debug("Pacing %s: waiting %.1fs to respect rpm limit", name, wait)
            self._sleep(wait)

    def _cooldown_wait(self, attempt: int) -> float:
        """Bounded wait before the next retry pass: at least until the earliest
        cooldown expires, at least the exponential backoff, capped."""
        now = self._clock()
        remaining = [t - now for t in self._cooldown_until.values() if t > now]
        earliest = min(remaining) if remaining else 0.0
        backoff = (2.0 ** attempt) + random.uniform(0.0, 1.0)
        return min(max(earliest, backoff), self.max_backoff_wait)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def complete(self, system: str, user: str) -> LLMResponse:
        self._check_and_reset_date()
        if self._request_count >= self.daily_limit:
            raise LLMBudgetExceeded(f"Daily limit of {self.daily_limit} requests reached")

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            saw_non_rate_limit_failure = False
            for provider in self.providers:
                if not provider.is_available():
                    continue
                if self._in_cooldown(provider.name):
                    continue
                self._pace(provider.name)
                self._last_call_at[provider.name] = self._clock()
                try:
                    resp = provider.complete(system, user)
                    self._request_count += 1
                    logger.info(
                        "LLM response from %s (%d tokens)", provider.name, resp.tokens_used
                    )
                    return resp
                except Exception as exc:
                    last_exc = exc
                    if _is_rate_limit(exc):
                        cooldown = _retry_after_seconds(exc, self.cooldown_seconds)
                        self._cooldown_until[provider.name] = self._clock() + cooldown
                        logger.warning(
                            "Provider %s rate-limited (429) — cooldown %.0fs, trying next",
                            provider.name,
                            cooldown,
                        )
                    else:
                        saw_non_rate_limit_failure = True
                        logger.warning("Provider %s failed: %s", provider.name, exc)

            # A retry pass only makes sense while some provider is cooling down
            # (rate limits recover with time; other errors don't).
            any_cooling = any(self._in_cooldown(p.name) for p in self.providers)
            if not any_cooling or attempt >= self.max_retries:
                break
            wait = self._cooldown_wait(attempt)
            logger.info(
                "All providers unavailable (rate-limited) — retry %d/%d in %.1fs",
                attempt + 1,
                self.max_retries,
                wait,
            )
            self._sleep(wait)

        rate_limited_only = not saw_non_rate_limit_failure and (
            (last_exc is not None and _is_rate_limit(last_exc))
            or any(self._in_cooldown(p.name) for p in self.providers)
        )
        if rate_limited_only:
            raise LLMRateLimited(
                "All providers rate-limited (429); retries exhausted"
            ) from last_exc
        raise LLMAllProvidersFailed(f"All providers failed. Last error: {last_exc}")
