from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from app.llm.gateway import (
    LLMAllProvidersFailed,
    LLMBudgetExceeded,
    LLMGateway,
    LLMRateLimited,
)
from app.llm.providers.base import LLMResponse

_OK = LLMResponse(provider="p1", model="m", content='{"ok":true}', parsed={"ok": True})


def _mock_provider(name: str, available: bool = True, side_effect=None):
    p = MagicMock()
    p.name = name
    p.is_available.return_value = available
    if side_effect:
        p.complete.side_effect = side_effect
    else:
        p.complete.return_value = _OK
    return p


def _http_429(retry_after: str | None = None) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://api.test/v1")
    headers = {"Retry-After": retry_after} if retry_after else {}
    resp = httpx.Response(429, headers=headers, request=req)
    return httpx.HTTPStatusError("429 Too Many Requests", request=req, response=resp)


class _FakeClock:
    """Monotonic clock advanced manually or by the injected sleep."""

    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def _gw(providers, clock: _FakeClock | None = None, **kwargs) -> LLMGateway:
    clock = clock or _FakeClock()
    kwargs.setdefault("daily_limit", 100)
    return LLMGateway(providers, sleep_fn=clock.sleep, clock=clock, **kwargs)


# ---------------------------------------------------------------------------
# Original behaviour
# ---------------------------------------------------------------------------


def test_gateway_uses_first_available_provider():
    p1 = _mock_provider("p1")
    p2 = _mock_provider("p2")
    gw = _gw([p1, p2])
    resp = gw.complete("sys", "user")
    assert resp.provider == "p1"
    p2.complete.assert_not_called()


def test_gateway_fallback_on_exception():
    p1 = _mock_provider("p1", side_effect=Exception("429 rate limit"))
    p2_resp = LLMResponse(provider="p2", model="m", content='{"ok":true}', parsed={"ok": True})
    p2 = _mock_provider("p2")
    p2.complete.return_value = p2_resp
    gw = _gw([p1, p2])
    resp = gw.complete("sys", "user")
    assert resp.provider == "p2"


def test_gateway_budget_exceeded():
    p1 = _mock_provider("p1")
    gw = _gw([p1], daily_limit=2)
    gw.complete("s", "u")
    gw.complete("s", "u")
    with pytest.raises(LLMBudgetExceeded):
        gw.complete("s", "u")


def test_gateway_all_providers_fail():
    p1 = _mock_provider("p1", side_effect=Exception("fail"))
    clock = _FakeClock()
    gw = _gw([p1], clock=clock)
    with pytest.raises(LLMAllProvidersFailed):
        gw.complete("s", "u")
    # Non-rate-limit failures do not trigger backoff retries
    assert clock.sleeps == []
    assert p1.complete.call_count == 1


def test_provider_unavailable_skipped():
    p1 = _mock_provider("p1", available=False)
    p2_resp = LLMResponse(provider="p2", model="m", content="{}", parsed={})
    p2 = _mock_provider("p2")
    p2.complete.return_value = p2_resp
    gw = _gw([p1, p2])
    resp = gw.complete("s", "u")
    assert resp.provider == "p2"
    p1.complete.assert_not_called()


def test_requests_today_counter():
    p1 = _mock_provider("p1")
    gw = _gw([p1], daily_limit=10)
    assert gw.requests_today() == 0
    gw.complete("s", "u")
    assert gw.requests_today() == 1


# ---------------------------------------------------------------------------
# (a) 429 → cooldown + fallback to the next provider
# ---------------------------------------------------------------------------


def test_429_falls_back_and_puts_provider_in_cooldown():
    p2_resp = LLMResponse(provider="p2", model="m", content="{}", parsed={})
    p1 = _mock_provider("p1", side_effect=_http_429(retry_after="30"))
    p2 = _mock_provider("p2")
    p2.complete.return_value = p2_resp
    clock = _FakeClock()
    gw = _gw([p1, p2], clock=clock)

    resp = gw.complete("s", "u")
    assert resp.provider == "p2"
    assert p1.complete.call_count == 1

    # Second call: p1 still cooling down (Retry-After=30) → not tried again
    resp = gw.complete("s", "u")
    assert resp.provider == "p2"
    assert p1.complete.call_count == 1


def test_429_cooldown_expires_after_retry_after():
    ok_p1 = LLMResponse(provider="p1", model="m", content="{}", parsed={})
    p1 = _mock_provider("p1", side_effect=[_http_429(retry_after="30"), ok_p1])
    p2 = _mock_provider("p2")
    p2.complete.return_value = LLMResponse(provider="p2", model="m", content="{}", parsed={})
    clock = _FakeClock()
    gw = _gw([p1, p2], clock=clock)

    assert gw.complete("s", "u").provider == "p2"
    clock.t += 31.0  # past the Retry-After window
    assert gw.complete("s", "u").provider == "p1"
    assert p1.complete.call_count == 2


def test_429_without_retry_after_uses_default_cooldown():
    p1 = _mock_provider("p1", side_effect=[_http_429(), _OK])
    p2 = _mock_provider("p2")
    p2.complete.return_value = LLMResponse(provider="p2", model="m", content="{}", parsed={})
    clock = _FakeClock()
    gw = _gw([p1, p2], clock=clock, cooldown_seconds=45.0)

    gw.complete("s", "u")
    clock.t += 44.0
    assert gw.complete("s", "u").provider == "p2"  # still cooling
    clock.t += 2.0
    assert gw.complete("s", "u").provider == "p1"  # recovered


# ---------------------------------------------------------------------------
# (b) all providers in cooldown → bounded backoff retries, then error
# ---------------------------------------------------------------------------


def test_all_rate_limited_retries_then_raises_rate_limited():
    p1 = _mock_provider("p1", side_effect=_http_429())
    clock = _FakeClock()
    gw = _gw([p1], clock=clock, max_retries=2, cooldown_seconds=60.0)

    with pytest.raises(LLMRateLimited):
        gw.complete("s", "u")

    # initial pass + 2 retry passes (sleep advances the clock past the cooldown)
    assert p1.complete.call_count == 3
    assert len(clock.sleeps) == 2
    for s in clock.sleeps:
        assert 0.0 < s <= gw.max_backoff_wait


def test_all_rate_limited_recovers_on_retry():
    p1 = _mock_provider("p1", side_effect=[_http_429(), _OK])
    clock = _FakeClock()
    gw = _gw([p1], clock=clock, max_retries=3)

    resp = gw.complete("s", "u")
    assert resp.parsed == {"ok": True}
    assert p1.complete.call_count == 2
    assert len(clock.sleeps) == 1


def test_rate_limited_is_all_providers_failed_subclass():
    assert issubclass(LLMRateLimited, LLMAllProvidersFailed)


def test_all_cooling_at_entry_raises_rate_limited():
    """A second call while every provider is still cooling must not hammer them."""
    p1 = _mock_provider("p1", side_effect=_http_429(retry_after="600"))
    clock = _FakeClock()
    gw = _gw([p1], clock=clock, max_retries=1, max_backoff_wait=5.0)

    with pytest.raises(LLMRateLimited):
        gw.complete("s", "u")
    calls_after_first = p1.complete.call_count

    with pytest.raises(LLMRateLimited):
        gw.complete("s", "u")
    # Cooldown (600s) far exceeds the bounded waits → no further provider calls
    assert p1.complete.call_count == calls_after_first


# ---------------------------------------------------------------------------
# Pacing (per-provider rpm)
# ---------------------------------------------------------------------------


def test_pacing_spaces_out_calls_to_same_provider():
    p1 = _mock_provider("p1")
    clock = _FakeClock()
    gw = _gw([p1], clock=clock, rpm={"p1": 30})  # min interval 2s

    gw.complete("s", "u")
    assert clock.sleeps == []  # first call is immediate

    gw.complete("s", "u")
    assert len(clock.sleeps) == 1
    assert clock.sleeps[0] == pytest.approx(2.0)


def test_pacing_skipped_when_interval_elapsed():
    p1 = _mock_provider("p1")
    clock = _FakeClock()
    gw = _gw([p1], clock=clock, rpm={"p1": 30})

    gw.complete("s", "u")
    clock.t += 5.0
    gw.complete("s", "u")
    assert clock.sleeps == []
