"""Backtest: replay historical OHLCV through the multi-agent pipeline."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from app.agents.adaptive_weights import adapt_weights, realized_volatility_pct
from app.agents.debate import apply_debate_proxy
from app.agents.deterministic import deterministic_views
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
from app.orchestrator import apply_trend_gate

logger = logging.getLogger(__name__)


class _RaisingGateway:
    """Gateway stub that always raises, forcing the PM's rule-based fallback.

    Used in deterministic backtest mode: specialist views are computed from data
    and the PortfolioManager aggregates them with its deterministic fallback
    rules — no LLM involved.
    """

    def complete(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("deterministic mode: LLM disabled")


@dataclass
class BacktestResult:
    asset: str
    trades: list[dict] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    final_balance: float = 0.0
    initial_balance: float = 0.0
    btc_bh_return_pct: float | None = None

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

    @property
    def profit_factor(self) -> float:
        """Gross profit / gross loss. Returns inf if no losses."""
        gross_profit = sum(t["pnl"] for t in self.trades if t.get("pnl", 0) > 0)
        gross_loss = abs(sum(t["pnl"] for t in self.trades if t.get("pnl", 0) < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else 1.0
        return gross_profit / gross_loss

    @property
    def sharpe(self) -> float:
        """Simplified Sharpe (annualised). Uses equity_curve step returns."""
        if len(self.equity_curve) < 2:
            return 0.0
        balances = [e["balance"] for e in self.equity_curve]
        returns = [
            (balances[i] - balances[i - 1]) / balances[i - 1]
            for i in range(1, len(balances))
            if balances[i - 1] != 0
        ]
        if not returns:
            return 0.0
        import statistics

        mean_r = statistics.mean(returns)
        std_r = statistics.stdev(returns) if len(returns) > 1 else 0.0
        if std_r == 0:
            return 0.0
        # Annualise assuming hourly candles (8760 periods/year)
        return (mean_r / std_r) * (8760 ** 0.5)

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
            "profit_factor": (
                round(self.profit_factor, 3)
                if self.profit_factor != float("inf")
                else "inf"
            ),
            "sharpe": round(self.sharpe, 3),
            "btc_bh_return_pct": (
                round(self.btc_bh_return_pct, 2)
                if self.btc_bh_return_pct is not None
                else None
            ),
        }


def run_backtest(
    asset: str,
    timeframe: str,
    df_ohlcv: pd.DataFrame,
    settings: Settings,
    gateway: Any,
    window: int = 100,
    step: int = 1,
    deterministic: bool = False,
    forecast_every: int | None = None,
    forecast_cache: dict | None = None,
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
    deterministic:  When True, derive every AgentView directly from the data
                (MACD/RSI/pivot, Prophet, F&G, …) and let the PortfolioManager
                aggregate with its rule-based fallback — no LLM calls. This is the
                mode that actually opens/closes positions for offline backtests.
    forecast_every:  In deterministic mode, recompute the (slow) Prophet forecast
                only every N steps and reuse it in between. ``None`` falls back to
                ``settings.forecast_refit_every``; set 0 to disable the forecast.
    forecast_cache:  Optional dict shared across runs on the SAME data: caches the
                forecast per step index so A/B comparisons don't refit Prophet
                for every flag combination.

    Feature flags (from ``settings``), both default OFF:
    - ``debate_enabled``: applies the deterministic debate proxy — conviction is
      penalised when bull and bear evidence are both strong (high agent
      disagreement) and untouched when one-sided. Backtests never call the LLM
      debate; the proxy makes the flag measurable offline.
    - ``adaptive_weights_enabled``: tilts agent weights per step based on the
      realized-volatility regime of the current OHLCV window (sum stays 1.0).

    Returns
    -------
    BacktestResult
    """
    if forecast_every is None:
        forecast_every = settings.forecast_refit_every

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
    sentiment_agent = SentimentAgent(
        gateway,
        extreme_only=settings.sentiment_extreme_only,
        extreme_threshold=settings.sentiment_extreme_threshold,
    )
    onchain_agent = OnChainAgent(gateway)
    news_agent = NewsAgent(gateway)
    # In deterministic mode the PM must fall back to its rule-based aggregator,
    # so give it a gateway that always raises.
    pm_agent = PortfolioManagerAgent(
        _RaisingGateway() if deterministic else gateway,
        weights=settings.agent_weights,
    )
    risk_manager = RiskManager(settings)

    equity_start_of_day: float = settings.paper_initial_balance
    n = len(df_ohlcv)
    cached_forecast: dict = {"degraded": True}

    for i in range(window, n, step):
        df_slice = df_ohlcv.iloc[i - window : i]
        current_candle = df_ohlcv.iloc[i - 1]
        mark_price = float(current_candle["close"])

        # ------------------------------------------------------------------
        # Build MarketContext without any live API calls
        # ------------------------------------------------------------------
        ohlcv_records = df_slice.reset_index().to_dict("records")

        indicators = compute_indicators(df_slice, settings.trend_ema_period)

        # Forecast: Prophet is expensive, so in deterministic mode recompute it
        # only every ``forecast_every`` steps and reuse the cached value between.
        if deterministic and forecast_every > 0:
            if (i - window) % forecast_every == 0:
                if forecast_cache is not None and i in forecast_cache:
                    cached_forecast = forecast_cache[i]
                else:
                    try:
                        cached_forecast = get_forecast(asset, timeframe, df_slice)
                    except Exception as exc:
                        logger.debug("Forecast failed at step %d: %s", i, exc)
                        cached_forecast = {"degraded": True}
                    if forecast_cache is not None:
                        forecast_cache[i] = cached_forecast
            forecast = cached_forecast
        else:
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
        # Build agent views (deterministic = from data, else via LLM agents)
        # ------------------------------------------------------------------
        if deterministic:
            views = deterministic_views(ctx)
        else:
            views = []
            for agent in (
                technical_agent,
                forecast_agent,
                sentiment_agent,
                onchain_agent,
                news_agent,
            ):
                try:
                    views.append(agent.analyze(ctx))
                except Exception as exc:
                    logger.debug("Agent %s failed at step %d: %s", agent.name, i, exc)

        # Position context so the PM can close on a signal flip (not only SL/TP)
        pos = broker.positions.get(asset)
        open_position: dict | None = None
        if pos is not None:
            direction = 1.0 if pos.side == "long" else -1.0
            upnl = (
                round((mark_price / pos.entry_price - 1.0) * 100 * direction, 2)
                if pos.entry_price
                else None
            )
            open_position = {
                "side": pos.side,
                "entry_price": pos.entry_price,
                "unrealized_pct": upnl,
            }

        # ------------------------------------------------------------------
        # Portfolio Manager → Trade Idea (+ trend filter gate)
        # ------------------------------------------------------------------
        # Regime-adaptive weights (feature-flagged, deterministic per step)
        if settings.adaptive_weights_enabled:
            closes = [float(c) for c in df_slice["close"].tolist()]
            vol_pct = realized_volatility_pct(closes, settings.adaptive_vol_lookback)
            pm_agent.weights = adapt_weights(
                settings.agent_weights,
                vol_pct,
                low_threshold=settings.adaptive_vol_low_pct,
                high_threshold=settings.adaptive_vol_high_pct,
                shift=settings.adaptive_shift,
            )

        try:
            idea = pm_agent.aggregate(views, asset, ctx, open_position=open_position)
            # Debate proxy (feature-flagged): penalise conviction on high
            # bull/bear disagreement; one-sided inputs pass through unchanged.
            if settings.debate_enabled:
                idea = apply_debate_proxy(
                    idea, views, pm_agent.weights,
                    max_penalty=settings.debate_max_penalty,
                )
            if settings.trend_filter_enabled:
                idea = apply_trend_gate(idea, asset, indicators)
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
                        broker.last_stop_at[asset] = datetime.now(tz=UTC).isoformat()
                    elif next_high >= pos.tp_price:
                        broker.close_position(asset, pos.tp_price)
                else:  # short
                    if next_high >= pos.sl_price:
                        broker.close_position(asset, pos.sl_price)
                        broker.last_stop_at[asset] = datetime.now(tz=UTC).isoformat()
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


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


class _NoLLMGateway:
    """Drop-in LLMGateway replacement that always returns hold (no API calls)."""

    class _Resp:
        content = (
            '{"action":"hold","target_size_pct":0.1,"conviction":0.3,'
            '"combined_rationale":"no-llm mode"}'
        )
        parsed: dict = {
            "signal": "neutral",
            "confidence": 0.0,
            "rationale": "no-llm mode",
        }

    def complete(self, system: str, user: str) -> _NoLLMGateway._Resp:
        return self._Resp()


def _fetch_ohlcv(
    asset: str, timeframe: str, start: str, end: str
) -> pd.DataFrame | None:
    """Fetch historical candles using ccxt (Binance)."""
    try:
        import ccxt

        exchange = ccxt.binance({"enableRateLimit": True})
        since = int(pd.Timestamp(start).timestamp() * 1000)
        end_ts = int(pd.Timestamp(end).timestamp() * 1000)
        all_candles = []
        while True:
            candles = exchange.fetch_ohlcv(
                asset, timeframe=timeframe, since=since, limit=1000
            )
            if not candles:
                break
            all_candles.extend(candles)
            last_ts = candles[-1][0]
            if last_ts >= end_ts:
                break
            since = last_ts + 1
        if not all_candles:
            return None
        df = pd.DataFrame(
            all_candles,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.set_index("timestamp")
        # Trim to requested window
        df = df[df.index <= pd.Timestamp(end, tz="UTC")]
        return df
    except Exception as exc:
        logger.error("Failed to fetch OHLCV: %s", exc)
        return None


def _write_markdown_report(path: Any, summary: dict, args: Any) -> None:
    lines = [
        f"# Backtest Report — {summary['asset']}",
        f"Period: {args.start} → {args.end} | Timeframe: {args.timeframe}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Initial balance | ${summary['initial_balance']:,.2f} |",
        f"| Final balance | ${summary['final_balance']:,.2f} |",
        f"| PnL | ${summary['pnl']:,.2f} ({summary['pnl_pct']:.2f}%) |",
        f"| BTC Buy & Hold | {summary.get('btc_bh_return_pct', 'N/A')}% |",
        f"| Trades | {summary['n_trades']} |",
        f"| Win rate | {summary['win_rate']:.1f}% |",
        f"| Max drawdown | {summary['max_drawdown_pct']:.1f}% |",
        f"| Profit factor | {summary['profit_factor']} |",
        f"| Sharpe (ann.) | {summary['sharpe']} |",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def _btc_bh_return(timeframe: str, start: str, end: str, df: pd.DataFrame) -> float | None:
    """BTC buy-and-hold return (%) over the same window."""
    btc_df = df if True else None  # df is BTC when asset==BTC/USDT; else refetch
    if btc_df is None or btc_df.empty:
        return None
    s = float(btc_df.iloc[0]["close"])
    e = float(btc_df.iloc[-1]["close"])
    return (e - s) / s * 100


def _comparison_table(on: dict, off: dict) -> str:
    """Render a side-by-side markdown table of two summaries."""
    rows = [
        ("PnL ($)", "pnl"),
        ("PnL (%)", "pnl_pct"),
        ("vs BTC B&H (%)", "btc_bh_return_pct"),
        ("Sharpe (ann.)", "sharpe"),
        ("Max drawdown (%)", "max_drawdown_pct"),
        ("Win rate (%)", "win_rate"),
        ("Profit factor", "profit_factor"),
        ("N trades", "n_trades"),
    ]
    lines = [
        "| Metric | Trend filter ON | Trend filter OFF |",
        "|--------|-----------------|------------------|",
    ]
    for label, key in rows:
        lines.append(f"| {label} | {on.get(key)} | {off.get(key)} |")
    return "\n".join(lines)


# Reference windows for the feature A/B comparison (same three regimes used
# in previous evaluations: bear, bull, choppy).
FEATURE_WINDOWS: dict[str, tuple[str, str]] = {
    "Bear 2022": ("2022-01-01", "2022-06-30"),
    "Bull 2023-24": ("2023-10-01", "2024-03-31"),
    "Choppy 2024": ("2024-08-01", "2024-11-30"),
}

# (label, debate_enabled, adaptive_weights_enabled)
FEATURE_COMBOS: list[tuple[str, bool, bool]] = [
    ("baseline", False, False),
    ("debate", True, False),
    ("adaptive", False, True),
    ("both", True, True),
]


def run_feature_comparison(
    asset: str,
    timeframe: str,
    settings: Settings,
    forecast_every: int | None,
    out_dir: Any,
) -> dict:
    """A/B the debate proxy and adaptive weights over the reference windows.

    Runs the deterministic backtest for every flag combination on each window,
    sharing a per-window forecast cache so Prophet is fitted once per step
    regardless of how many combos run. Writes a combined md+json report to
    ``out_dir`` and returns the results dict.
    """
    import json
    from pathlib import Path

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}

    for win_name, (start, end) in FEATURE_WINDOWS.items():
        logger.info("=== Window %s: %s → %s ===", win_name, start, end)
        df = _fetch_ohlcv(asset, timeframe, start, end)
        if df is None or df.empty:
            logger.error("No OHLCV for window %s — skipping", win_name)
            continue
        bh_pct = (float(df.iloc[-1]["close"]) / float(df.iloc[0]["close"]) - 1.0) * 100
        cache: dict = {}
        win_results: dict[str, dict] = {
            "_meta": {
                "start": start,
                "end": end,
                "candles": len(df),
                "buy_hold_pct": round(bh_pct, 2),
            }
        }
        for label, debate_on, adaptive_on in FEATURE_COMBOS:
            settings.debate_enabled = debate_on
            settings.adaptive_weights_enabled = adaptive_on
            res = run_backtest(
                asset=asset,
                timeframe=timeframe,
                df_ohlcv=df,
                settings=settings,
                gateway=_RaisingGateway(),
                window=100,
                deterministic=True,
                forecast_every=forecast_every,
                forecast_cache=cache,
            )
            summary = res.summary()
            summary["buy_hold_pct"] = round(bh_pct, 2)
            summary["alpha_pct"] = round(summary["pnl_pct"] - bh_pct, 2)
            win_results[label] = summary
            logger.info(
                "%s / %s: pnl=%.2f%% alpha=%.2f%% trades=%d",
                win_name, label, summary["pnl_pct"], summary["alpha_pct"],
                summary["n_trades"],
            )
        results[win_name] = win_results

    # Restore defaults so a reused Settings instance is not left mutated
    settings.debate_enabled = False
    settings.adaptive_weights_enabled = False

    asset_slug = asset.replace("/", "").replace(":", "")
    fc = forecast_every if forecast_every is not None else settings.forecast_refit_every
    lines = [
        "# Feature comparison — debate proxy & adaptive weights",
        f"Asset: {asset} | Timeframe: {timeframe} | Mode: deterministic (no LLM) "
        f"| forecast_every={fc}",
        "",
        "Combos: baseline (flags OFF), debate (debate_enabled), "
        "adaptive (adaptive_weights_enabled), both.",
        "",
    ]
    for win_name, win in results.items():
        meta = win["_meta"]
        lines += [
            f"## {win_name} ({meta['start']} → {meta['end']}) — "
            f"buy&hold {meta['buy_hold_pct']}%",
            "",
            "| Combo | PnL % | B&H % | Alpha % | Sharpe | Max DD % "
            "| Win rate % | Profit factor | Trades |",
            "|-------|-------|-------|---------|--------|----------"
            "|------------|---------------|--------|",
        ]
        for label, _, _ in FEATURE_COMBOS:
            s = win.get(label)
            if not s:
                continue
            lines.append(
                f"| {label} | {s['pnl_pct']} | {s['buy_hold_pct']} | {s['alpha_pct']} "
                f"| {s['sharpe']} | {s['max_drawdown_pct']} | {s['win_rate']} "
                f"| {s['profit_factor']} | {s['n_trades']} |"
            )
        lines.append("")

    md_path = out_dir / f"compare_features_{asset_slug}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    json_path = out_dir / f"compare_features_{asset_slug}.json"
    json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    logger.info("Feature comparison saved to %s and %s", md_path, json_path)
    return results


def main() -> None:
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description="Backtest the multi-agent trading system"
    )
    parser.add_argument(
        "--start", default=None, help="Start date YYYY-MM-DD (not needed with --compare-features)"
    )
    parser.add_argument(
        "--end", default=None, help="End date YYYY-MM-DD (not needed with --compare-features)"
    )
    parser.add_argument(
        "--asset", default="BTC/USDT", help="Asset to backtest (default BTC/USDT)"
    )
    parser.add_argument(
        "--timeframe", default="1h", help="Candle timeframe (default 1h)"
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Use rule-based fallback (no LLM calls, always holds)",
    )
    parser.add_argument(
        "--deterministic",
        action="store_true",
        help="Derive signals from data (no LLM) — actually trades",
    )
    parser.add_argument(
        "--forecast-every",
        type=int,
        default=None,
        help="Recompute Prophet forecast every N steps in deterministic mode "
        "(0 = no forecast; default settings.forecast_refit_every=24)",
    )
    parser.add_argument(
        "--trend-filter",
        choices=["on", "off", "default"],
        default="default",
        help="Override settings.trend_filter_enabled for this run",
    )
    parser.add_argument(
        "--compare-trend-filter",
        action="store_true",
        help="Run twice (trend filter ON vs OFF, deterministic) and compare",
    )
    parser.add_argument(
        "--compare-features",
        action="store_true",
        help="A/B the debate proxy and adaptive weights over the three "
        "reference windows (bear/bull/choppy), deterministic",
    )
    parser.add_argument(
        "--output",
        default="reports",
        help="Directory for the report (default reports/)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s"
    )

    settings = Settings()

    # ------------------------------------------------------------------ #
    # Feature comparison mode: fixed reference windows, no --start/--end
    # ------------------------------------------------------------------ #
    if args.compare_features:
        run_feature_comparison(
            asset=args.asset,
            timeframe=args.timeframe,
            settings=settings,
            forecast_every=args.forecast_every,
            out_dir=args.output,
        )
        return

    if not args.start or not args.end:
        parser.error("--start and --end are required (except with --compare-features)")

    # Build gateway: --deterministic/--compare use the raising gateway internally,
    # so only the LLM path needs a real (or no-llm) gateway.
    deterministic = args.deterministic or args.compare_trend_filter
    if deterministic:
        gateway: Any = _RaisingGateway()
    elif args.no_llm:
        gateway = _NoLLMGateway()
    else:
        from app.run import build_gateway

        gateway = build_gateway()

    # Fetch OHLCV once
    logger.info(
        "Fetching %s %s from %s to %s …",
        args.asset, args.timeframe, args.start, args.end,
    )
    df = _fetch_ohlcv(args.asset, args.timeframe, args.start, args.end)
    if df is None or df.empty:
        logger.error("No OHLCV data — cannot run backtest")
        sys.exit(1)
    logger.info("Got %d candles", len(df))

    # BTC buy-and-hold for the same window
    if args.asset != "BTC/USDT":
        btc_df = _fetch_ohlcv("BTC/USDT", args.timeframe, args.start, args.end)
    else:
        btc_df = df
    btc_bh = _btc_bh_return(args.timeframe, args.start, args.end, btc_df)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = args.start.replace("-", "") + "_" + args.end.replace("-", "")
    asset_slug = args.asset.replace("/", "").replace(":", "")

    def _run(trend_on: bool) -> dict:
        settings.trend_filter_enabled = trend_on
        res = run_backtest(
            asset=args.asset,
            timeframe=args.timeframe,
            df_ohlcv=df,
            settings=settings,
            gateway=gateway,
            window=100,
            deterministic=True,
            forecast_every=args.forecast_every,
        )
        res.btc_bh_return_pct = btc_bh
        return res.summary()

    # ------------------------------------------------------------------ #
    # Compare mode: two deterministic runs, trend filter ON vs OFF
    # ------------------------------------------------------------------ #
    if args.compare_trend_filter:
        logger.info("=== Run 1/2: trend filter ON ===")
        summary_on = _run(trend_on=True)
        logger.info("=== Run 2/2: trend filter OFF ===")
        summary_off = _run(trend_on=False)

        table = _comparison_table(summary_on, summary_off)
        combined = {
            "asset": args.asset,
            "period": f"{args.start} → {args.end}",
            "timeframe": args.timeframe,
            "trend_filter_on": summary_on,
            "trend_filter_off": summary_off,
        }
        json_path = out_dir / f"compare_trendfilter_{asset_slug}_{ts}.json"
        json_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
        md_path = out_dir / f"compare_trendfilter_{asset_slug}_{ts}.md"
        md_path.write_text(
            f"# Trend-filter comparison — {args.asset}\n"
            f"Period: {args.start} → {args.end} | Timeframe: {args.timeframe} "
            f"| BTC B&H: {btc_bh:.2f}%\n\n{table}\n",
            encoding="utf-8",
        )
        logger.info("Comparison:\n%s", table)
        logger.info("Saved %s and %s", json_path, md_path)
        return

    # ------------------------------------------------------------------ #
    # Single run
    # ------------------------------------------------------------------ #
    if args.trend_filter != "default":
        settings.trend_filter_enabled = args.trend_filter == "on"

    result = run_backtest(
        asset=args.asset,
        timeframe=args.timeframe,
        df_ohlcv=df,
        settings=settings,
        gateway=gateway,
        window=100,
        deterministic=deterministic,
        forecast_every=args.forecast_every,
    )
    result.btc_bh_return_pct = btc_bh

    summary = result.summary()
    logger.info("Backtest result: %s", json.dumps(summary, indent=2))

    suffix = ""
    if args.trend_filter != "default":
        suffix = f"_trend{args.trend_filter.upper()}"
    report_path = out_dir / f"backtest_{asset_slug}_{ts}{suffix}.json"
    report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("Report saved to %s", report_path)

    md_path = out_dir / f"backtest_{asset_slug}_{ts}{suffix}.md"
    _write_markdown_report(md_path, summary, args)
    logger.info("Markdown report saved to %s", md_path)


if __name__ == "__main__":
    main()
