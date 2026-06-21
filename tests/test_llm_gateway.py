from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.llm.gateway import LLMAllProvidersFailed, LLMBudgetExceeded, LLMGateway
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


def test_gateway_uses_first_available_provider():
    p1 = _mock_provider("p1")
    p2 = _mock_provider("p2")
    gw = LLMGateway([p1, p2], daily_limit=100)
    resp = gw.complete("sys", "user")
    assert resp.provider == "p1"
    p2.complete.assert_not_called()


def test_gateway_fallback_on_exception():
    p1 = _mock_provider("p1", side_effect=Exception("429 rate limit"))
    p2_resp = LLMResponse(provider="p2", model="m", content='{"ok":true}', parsed={"ok": True})
    p2 = _mock_provider("p2")
    p2.complete.return_value = p2_resp
    gw = LLMGateway([p1, p2], daily_limit=100)
    resp = gw.complete("sys", "user")
    assert resp.provider == "p2"


def test_gateway_budget_exceeded():
    p1 = _mock_provider("p1")
    gw = LLMGateway([p1], daily_limit=2)
    gw.complete("s", "u")
    gw.complete("s", "u")
    with pytest.raises(LLMBudgetExceeded):
        gw.complete("s", "u")


def test_gateway_all_providers_fail():
    p1 = _mock_provider("p1", side_effect=Exception("fail"))
    gw = LLMGateway([p1], daily_limit=100)
    with pytest.raises(LLMAllProvidersFailed):
        gw.complete("s", "u")


def test_provider_unavailable_skipped():
    p1 = _mock_provider("p1", available=False)
    p2_resp = LLMResponse(provider="p2", model="m", content="{}", parsed={})
    p2 = _mock_provider("p2")
    p2.complete.return_value = p2_resp
    gw = LLMGateway([p1, p2], daily_limit=100)
    resp = gw.complete("s", "u")
    assert resp.provider == "p2"
    p1.complete.assert_not_called()


def test_requests_today_counter():
    p1 = _mock_provider("p1")
    gw = LLMGateway([p1], daily_limit=10)
    assert gw.requests_today() == 0
    gw.complete("s", "u")
    assert gw.requests_today() == 1
