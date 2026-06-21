"""Backtest: replay historical OHLCV through the multi-agent pipeline."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.agents.forecast_agent import ForecastAgent
from app.agents.news_agent import NewsAgent
from app.agents.onchain import OnChainAgent
from app.agents.portfolio_manager import PortfolioManagerAgent
from app.agents.risk_manager import RiskManager
from app.agents.sentiment_agent import SentimentAgent
from app.agents.technical import TechnicalAgent
from app.broker.paper import PaperBroker
from app.config import Settings
from app.data.context import MarketContext
from app.data.forecast import get_forecast
from app.data.indicators import compute_indicators

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    asset: str
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    final_balance: float = 0.0
    initial_balance: float = 0.0

    @property
    def pnl(self) -> float:
        return self.final_balance - self.initial_balance

    @property
    def pnl_pct(self) -> float:
        return self.pnl / self.initial_balance if self.initial_balance else 0.0

    @property
    def n_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        wins = [t for t in self.trades if t.get("pnl", 0) > 0]
        return len(wins) / len(self.trades) if self.trades else 0.0

    @property
    def max_drawdown(self) -> float:
        if not self.equity_curve:
            return 0.0
        balances = [e["balance"] for e in self.equity_curve]
        peak = balances[0]
        max_dd = 0.0
        for b in balances:
            peak = max(peak, b)
            dd = (peak - b) / peak if peak else 0.0
            max_dd = max(max_dd, dd)
        return max_dd

    def summary(self) -> dict:
        return {
            "asset": self.asset,
            "initial_balance": self.initial_balance,
            "final_balance": round(self.final_balance, 2),
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl_pct * 100, 2),
            "n_trades": self.n_trades,
            "win_rate": round(self.win_rate * 100, 2),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
        }


def run_backtest(
    asset: str,
    timeframe: str,
    df_ohlcv: pd.DataFrame,
    settings: Settings,
    gateway: Any,
    window: int = 100,
    step: int = 1,
) -> BacktestResult:
    """Replay historical OHLCV through the full multi-agent pipeline.

    Parameters
    ----------
    asset:      Trading pair, e.g. ``"BTC/USDT"``.
    timeframe:  Candle timeframe string, e.g. ``"1h"``.
    df_ohlcv:   Full historical DataFrame with columns open/high/low/close/volume
                and a timestamp index.
    settings:   Project ``Settings`` instance (risk limits, initial balance …).
    gateway:    ``LLMGateway`` (or mock) used by every agent.
    window:     Number of candles fed to indicators/forecast at each step.
    step:       How many candles to advance per iteration.

    Returns
    -------
    BacktestResult
    """
    broker = PaperBroker(
        initial_balance=settings.paper_initial_balance,
        fee_pct=settings.paper_fee_pct,
        slippage_pct=settings.paper_slippage_pct,
    )
    result = BacktestResult(
        asset=asset,
        initial_balance=settings.paper_initial_balance,
    )

    # Instantiate agents once (they are stateless per analyze() call)
    technical_agent = TechnicalAgent(gateway)
    forecast_agent = ForecastAgent(gateway)
    sentiment_agent = SentimentAgent(gateway)
    onchain_agent = OnChainAgent(gateway)
    news_agent = NewsAgent(gateway)
    pm_agent = PortfolioManagerAgent(gateway, weights=settings.agent_weights)
    risk_manager = RiskManager(settings)

    equity_start_of_day: float = settings.paper_initial_balance
    n = len(df_ohlcv)

    for i in range(window, n, step):
        df_slice = df_ohlcv.iloc[i - window : i]
        current_candle = df_ohlcv.iloc[i - 1]
        mark_price = float(current_candle["close"])

        # ------------------------------------------------------------------
        # Build MarketContext without any live API calls
        # ------------------------------------------------------------------
        ohlcv_records = df_slice.reset_index().to_dict("records")

        indicators = compute_indicators(df_slice)

        try:
            forecast = get_forecast(asset, timeframe, df_slice)
        except Exception as exc:
            logger.debug("Forecast failed at step %d: %s", i, exc)
            forecast = {"degraded": True}

        ctx = MarketContext(
            asset=asset,
            timeframe=timeframe,
            ohlcv=ohlcv_records,
            indicators=indicators,
            forecast=forecast,
            fear_and_greed={},
            whale_events=[],
            news_headlines=[],
            degraded_sources=["fear_and_greed", "whale", "news"],
        )

        # ------------------------------------------------------------------
        # Run specialist agents
        # ------------------------------------------------------------------
        views = []
        for agent in (
            technical_agent,
            forecast_agent,
            sentiment_agent,
            onchain_agent,
            news_agent,
        ):
            try:
                view = agent.analyze(ctx)
                views.append(view)
            except Exception as exc:
                logger.debug("Agent %s failed at step %d: %s", agent.name, i, exc)

        # ------------------------------------------------------------------
        # Portfolio Manager → Trade Idea
        # ------------------------------------------------------------------
        try:
            idea = pm_agent.aggregate(views, asset, ctx)
        except Exception as exc:
            logger.debug("PortfolioManager failed at step %d: %s", i, exc)
            # Skip this step — leave positions as-is
            result.equity_curve.append({"step": i, "balance": broker.get_balance()})
            continue

        # ------------------------------------------------------------------
        # Risk Manager → Validated Order
        # ------------------------------------------------------------------
        try:
            order = risk_manager.evaluate(idea, broker, mark_price, equity_start_of_day)
        except Exception as exc:
            logger.debug("RiskManager failed at step %d: %s", i, exc)
            result.equity_curve.append({"step": i, "balance": broker.get_balance()})
            continue

        # ------------------------------------------------------------------
        # Execute on PaperBroker
        # ------------------------------------------------------------------
        if not order.veto:
            action = order.action
            if action == "open_long":
                broker.place_order(
                    asset=asset,
                    side="long",
                    size_pct=order.size_pct,
                    mark_price=mark_price,
                    sl_price=order.sl_price,
                    tp_price=order.tp_price,
                )
            elif action == "open_short":
                broker.place_order(
                    asset=asset,
                    side="short",
                    size_pct=order.size_pct,
                    mark_price=mark_price,
                    sl_price=order.sl_price,
                    tp_price=order.tp_price,
                )
            elif action == "close":
                broker.close_position(asset, mark_price)

        # ------------------------------------------------------------------
        # Check SL/TP using the NEXT candle's high/low
        # ------------------------------------------------------------------
        next_idx = i  # df_ohlcv.iloc[i] is the candle *after* current window
        if next_idx < n:
            next_candle = df_ohlcv.iloc[next_idx]
            next_high = float(next_candle["high"])
            next_low = float(next_candle["low"])
            pos = broker.positions.get(asset)
            if pos is not None:
                if pos.side == "long":
                    if next_low <= pos.sl_price:
                        broker.close_position(asset, pos.sl_price)
                    elif next_high >= pos.tp_price:
                        broker.close_position(asset, pos.tp_price)
                else:  # short
                    if next_high >= pos.sl_price:
                        broker.close_position(asset, pos.sl_price)
                    elif next_low <= pos.tp_price:
                        broker.close_position(asset, pos.tp_price)

        # ------------------------------------------------------------------
        # Record equity curve
        # ------------------------------------------------------------------
        result.equity_curve.append({"step": i, "balance": broker.get_balance()})

    # Finalize
    result.trades = list(broker.trade_history)
    result.final_balance = broker.get_balance()
    return result


def run_backtest_multi(
    assets: list[str],
    timeframe: str,
    settings: Settings,
    gateway: Any,
    df_map: dict[str, pd.DataFrame] | None = None,
    **kwargs: Any,
) -> list[BacktestResult]:
    """Run ``run_backtest`` for each asset and return all results.

    Parameters
    ----------
    assets:     List of trading pairs.
    timeframe:  Candle timeframe string.
    settings:   Project ``Settings`` instance.
    gateway:    ``LLMGateway`` (or mock).
    df_map:     Optional ``{asset: df_ohlcv}`` dict.  When not supplied the
                caller must provide ``df_ohlcv`` via ``kwargs`` — which only
                makes sense for a single asset.  Pass ``df_map`` for multi-
                asset runs.
    **kwargs:   Forwarded verbatim to ``run_backtest`` (e.g. ``window``,
                ``step``).
    """
    results: list[BacktestResult] = []
    for asset in assets:
        df = (df_map or {}).get(asset)
        if df is None:
            df = kwargs.pop("df_ohlcv", None)
        if df is None:
            logger.warning("No OHLCV data for %s — skipping", asset)
            continue
        try:
            res = run_backtest(asset, timeframe, df, settings, gateway, **kwargs)
            results.append(res)
        except Exception as exc:
            logger.error("Backtest for %s failed: %s", asset, exc)
    return results
