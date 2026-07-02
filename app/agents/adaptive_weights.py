"""Regime-adaptive agent weights.

Research on multi-agent trading ensembles suggests fixed agent weights are
sub-optimal across market regimes: in high-volatility phases sentiment/news
carry more signal, while in calm phases technical structure dominates. This
module derives a realized-volatility regime from the OHLCV already present in
the MarketContext (no new data sources) and tilts the base weights
accordingly — deterministically, so the feature is backtestable.
"""
from __future__ import annotations

import statistics

# Multiplicative tilt targets per regime. Only agents listed here move; the
# rest keep their base weight before the final re-normalisation.
_HIGH_VOL_TILT = {"technical": -1.0, "sentiment": +1.0, "news": +1.0}
_LOW_VOL_TILT = {"technical": +1.0, "sentiment": -1.0, "news": -1.0}

_MIN_WEIGHT = 0.02


def realized_volatility_pct(closes: list[float], lookback: int = 24) -> float | None:
    """Std-dev of per-bar close-to-close returns over the last ``lookback`` bars.

    Returns None when there is not enough data (< 3 usable returns).
    """
    usable = [c for c in closes if c and c > 0][-(lookback + 1):]
    if len(usable) < 4:
        return None
    returns = [usable[i] / usable[i - 1] - 1.0 for i in range(1, len(usable))]
    if len(returns) < 3:
        return None
    return statistics.stdev(returns)


def volatility_regime(
    vol_pct: float | None,
    low_threshold: float = 0.004,
    high_threshold: float = 0.009,
) -> str:
    """Classify per-bar return volatility into ``low`` / ``normal`` / ``high``."""
    if vol_pct is None:
        return "normal"
    if vol_pct >= high_threshold:
        return "high"
    if vol_pct <= low_threshold:
        return "low"
    return "normal"


def adapt_weights(
    base_weights: dict[str, float],
    vol_pct: float | None,
    low_threshold: float = 0.004,
    high_threshold: float = 0.009,
    shift: float = 0.35,
) -> dict[str, float]:
    """Return regime-tilted weights, always re-normalised to sum to 1.0.

    High-vol regime: sentiment/news scaled up by ``1 + shift``, technical down
    by ``1 - shift``. Low-vol: the reverse. Normal regime (or missing data):
    base weights unchanged apart from normalisation. Weights never drop below
    ``_MIN_WEIGHT`` before normalisation, keeping every agent in play.
    """
    regime = volatility_regime(vol_pct, low_threshold, high_threshold)
    shift = max(0.0, min(0.9, shift))
    tilt = {"high": _HIGH_VOL_TILT, "low": _LOW_VOL_TILT}.get(regime, {})

    adapted: dict[str, float] = {}
    for agent, w in base_weights.items():
        factor = 1.0 + shift * tilt.get(agent, 0.0)
        adapted[agent] = max(_MIN_WEIGHT, w * factor)

    total = sum(adapted.values()) or 1.0
    return {agent: w / total for agent, w in adapted.items()}
