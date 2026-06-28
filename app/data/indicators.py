from __future__ import annotations

import pandas as pd


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    # No losses -> RSI 100; no gains -> RSI 0.
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    rsi = rsi.where(avg_gain != 0.0, 0.0)
    return rsi


def compute_indicators(df: pd.DataFrame, trend_ema_period: int = 50) -> dict:
    """Compute MACD (12/26/9), RSI (14) and classic pivot points.

    Pure-pandas implementation (no external TA library) so it installs
    cleanly on any Python version. Returns None values on bad/empty input.
    """
    null_result: dict = {
        "macd": None,
        "macd_signal": None,
        "macd_hist": None,
        "rsi": None,
        "pivot": None,
        "r1": None,
        "s1": None,
        "r2": None,
        "s2": None,
        "trend_ema": None,
        "last_close": None,
    }
    required = {"open", "high", "low", "close", "volume"}
    if df is None or df.empty or not required.issubset(set(df.columns)):
        return null_result

    try:
        close = df["close"].astype(float)

        ema_fast = _ema(close, 12)
        ema_slow = _ema(close, 26)
        macd_line = ema_fast - ema_slow
        signal_line = _ema(macd_line, 9)
        hist_line = macd_line - signal_line
        rsi_series = _rsi(close, 14)
        trend_ema_series = _ema(close, trend_ema_period)

        last = df.iloc[-1]
        h, lo, c = float(last["high"]), float(last["low"]), float(last["close"])
        pivot = (h + lo + c) / 3
        r1 = 2 * pivot - lo
        s1 = 2 * pivot - h
        r2 = pivot + (h - lo)
        s2 = pivot - (h - lo)

        def last_val(series: pd.Series) -> float | None:
            v = series.dropna()
            return float(v.iloc[-1]) if not v.empty else None

        return {
            "macd": last_val(macd_line),
            "macd_signal": last_val(signal_line),
            "macd_hist": last_val(hist_line),
            "rsi": last_val(rsi_series),
            "pivot": pivot,
            "r1": r1,
            "s1": s1,
            "r2": r2,
            "s2": s2,
            "trend_ema": last_val(trend_ema_series),
            "last_close": float(c),
        }
    except Exception:
        return null_result
