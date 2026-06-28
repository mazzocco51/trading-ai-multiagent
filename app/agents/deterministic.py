"""Deterministic, LLM-free signal derivation for fast backtesting.

Each function maps a :class:`MarketContext` to an :class:`AgentView` using only
the numeric data already in the context (indicators, Prophet forecast, fear &
greed, whale events, headlines). No network or LLM calls — suitable for
replaying thousands of candles quickly while still opening/closing positions.
"""
from __future__ import annotations

from app.agents.base import AgentView
from app.data.context import MarketContext


def _neutral(name: str, asset: str, rationale: str, conf: float = 0.0) -> AgentView:
    return AgentView(
        agent=name, asset=asset, signal="neutral", confidence=conf, rationale=rationale
    )


def technical_view(ctx: MarketContext) -> AgentView:
    """Momentum/trend signal from MACD histogram, RSI and pivot position."""
    ind = ctx.indicators or {}
    macd_hist = ind.get("macd_hist")
    rsi = ind.get("rsi")
    pivot = ind.get("pivot")
    last_close = ind.get("last_close")
    if last_close is None and ctx.ohlcv:
        last_close = ctx.ohlcv[-1].get("close")
    if macd_hist is None or rsi is None or last_close is None:
        return _neutral("technical", ctx.asset, "indicators unavailable")

    score = 0.0
    score += 1.0 if macd_hist > 0 else -1.0            # MACD momentum
    score += max(-1.0, min(1.0, (rsi - 50.0) / 50.0))  # RSI trend bias
    if pivot:
        score += 0.5 if last_close > pivot else -0.5   # intraday pivot

    norm = max(-1.0, min(1.0, score / 2.5))
    if norm > 0.15:
        signal = "long"
    elif norm < -0.15:
        signal = "short"
    else:
        signal = "neutral"
    return AgentView(
        agent="technical",
        asset=ctx.asset,
        signal=signal,
        confidence=min(1.0, abs(norm)),
        rationale=f"MACD_hist={macd_hist:.4f}, RSI={rsi:.1f}, score={norm:.2f}",
        extra={"score": norm},
    )


def forecast_view(ctx: MarketContext) -> AgentView:
    """Directional signal from the Prophet forecast (expected move)."""
    fc = ctx.forecast or {}
    if not fc or fc.get("degraded"):
        return _neutral("forecast", ctx.asset, "forecast degraded")
    move = fc.get("expected_move_pct")
    conf = float(fc.get("confidence") or 0.0)
    if move is None:
        return _neutral("forecast", ctx.asset, "no expected move")
    if move > 0:
        signal = "long"
    elif move < 0:
        signal = "short"
    else:
        signal = "neutral"
    return AgentView(
        agent="forecast",
        asset=ctx.asset,
        signal=signal,
        confidence=conf,
        rationale=f"Prophet expected_move={move:.4%}, model_conf={conf:.2f}",
        extra={"expected_move_pct": move},
    )


def sentiment_view(ctx: MarketContext) -> AgentView:
    """Contrarian signal from the Fear & Greed index extremes."""
    fng = ctx.fear_and_greed or {}
    val = fng.get("value")
    if val is None:
        return _neutral("sentiment", ctx.asset, "fear & greed unavailable")
    val = int(val)
    if val <= 25:  # extreme fear → contrarian long
        conf = min(1.0, (25 - val) / 25.0 + 0.4)
        return AgentView(
            agent="sentiment", asset=ctx.asset, signal="long",
            confidence=conf, rationale=f"Extreme fear ({val}) → contrarian long",
        )
    if val >= 75:  # extreme greed → contrarian short
        conf = min(1.0, (val - 75) / 25.0 + 0.4)
        return AgentView(
            agent="sentiment", asset=ctx.asset, signal="short",
            confidence=conf, rationale=f"Extreme greed ({val}) → contrarian short",
        )
    return _neutral("sentiment", ctx.asset, f"F&G neutral ({val})")


def onchain_view(ctx: MarketContext) -> AgentView:
    """Exchange-flow pressure from whale events (neutral when no data)."""
    events = ctx.whale_events or []
    if not events:
        return _neutral("onchain", ctx.asset, "no whale events", conf=0.1)
    inflow = sum(
        1 for e in events
        if str(e.get("type", "")).lower() in {"deposit", "inflow", "sell"}
    )
    outflow = sum(
        1 for e in events
        if str(e.get("type", "")).lower() in {"withdrawal", "outflow", "buy"}
    )
    if outflow > inflow:
        return AgentView(
            agent="onchain", asset=ctx.asset, signal="long",
            confidence=0.3, rationale="net exchange outflow (bullish)",
        )
    if inflow > outflow:
        return AgentView(
            agent="onchain", asset=ctx.asset, signal="short",
            confidence=0.3, rationale="net exchange inflow (bearish)",
        )
    return _neutral("onchain", ctx.asset, "balanced whale flow", conf=0.1)


def news_view(ctx: MarketContext) -> AgentView:
    """News headlines are not scored deterministically — stay neutral."""
    headlines = ctx.news_headlines or []
    if not headlines:
        return _neutral("news", ctx.asset, "no news", conf=0.1)
    return _neutral("news", ctx.asset, "news unscored in deterministic mode", conf=0.1)


DETERMINISTIC_VIEWS = {
    "technical": technical_view,
    "forecast": forecast_view,
    "sentiment": sentiment_view,
    "onchain": onchain_view,
    "news": news_view,
}


def deterministic_views(ctx: MarketContext) -> list[AgentView]:
    """Run every deterministic specialist over the context."""
    return [fn(ctx) for fn in DETERMINISTIC_VIEWS.values()]
