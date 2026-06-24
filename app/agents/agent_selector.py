from __future__ import annotations

from typing import Literal

# Agents that are crypto-specific (Fear & Greed index, whale alerts, etc.)
# These are excluded when running against stock symbols.
CRYPTO_ONLY_AGENTS: set[str] = {"onchain", "sentiment"}


def get_agents_for_asset_class(asset_class: Literal["crypto", "stock"]) -> list[str]:
    """Return list of agent names applicable for the given asset class."""
    all_agents = ["technical", "forecast", "sentiment", "onchain", "news"]
    if asset_class == "stock":
        return [a for a in all_agents if a not in CRYPTO_ONLY_AGENTS]
    return all_agents


def get_weights_for_asset_class(
    weights: dict[str, float],
    asset_class: Literal["crypto", "stock"],
) -> dict[str, float]:
    """Return re-normalized weights for the applicable agents.

    Filters *weights* to only the agents valid for *asset_class*, then
    re-normalises so that the returned weights sum to 1.0.
    """
    applicable = set(get_agents_for_asset_class(asset_class))
    filtered = {k: v for k, v in weights.items() if k in applicable}
    total = sum(filtered.values()) or 1.0
    return {k: v / total for k, v in filtered.items()}
