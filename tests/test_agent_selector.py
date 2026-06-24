from __future__ import annotations

from app.agents.agent_selector import get_agents_for_asset_class, get_weights_for_asset_class


def test_get_agents_crypto():
    """Crypto returns all 5 agents."""
    agents = get_agents_for_asset_class("crypto")
    assert set(agents) == {"technical", "forecast", "sentiment", "onchain", "news"}
    assert len(agents) == 5


def test_get_agents_stock():
    """Stock excludes onchain and sentiment."""
    agents = get_agents_for_asset_class("stock")
    assert "onchain" not in agents
    assert "sentiment" not in agents
    assert "technical" in agents
    assert "forecast" in agents
    assert "news" in agents


def test_weights_renormalized():
    """For stocks, filtered weights should sum to ~1.0."""
    weights = {
        "technical": 0.30,
        "forecast": 0.20,
        "sentiment": 0.20,
        "onchain": 0.15,
        "news": 0.15,
    }
    result = get_weights_for_asset_class(weights, "stock")

    # Only technical, forecast, news remain
    assert "onchain" not in result
    assert "sentiment" not in result
    total = sum(result.values())
    assert abs(total - 1.0) < 1e-9
