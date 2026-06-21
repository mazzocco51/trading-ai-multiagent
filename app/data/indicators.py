from __future__ import annotations

import pandas as pd


def compute_indicators(df: pd.DataFrame) -> dict:
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
    }
    required = {"open", "high", "low", "close", "volume"}
    if df is None or df.empty or not required.issubset(set(df.columns)):
        return null_result

    try:
        import pandas_ta as ta

        macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
        rsi_series = ta.rsi(df["close"], length=14)

        last = df.iloc[-1]
        h, l, c = float(last["high"]), float(last["low"]), float(last["close"])
        pivot = (h + l + c) / 3
        r1 = 2 * pivot - l
        s1 = 2 * pivot - h
        r2 = pivot + (h - l)
        s2 = pivot - (h - l)

        macd_col = [c for c in macd_df.columns if c.startswith("MACD_") and "MACDs" not in c and "MACDh" not in c]
        sig_col = [c for c in macd_df.columns if "MACDs" in c]
        hist_col = [c for c in macd_df.columns if "MACDh" in c]

        def last_val(series_or_df, col_list=None):
            if col_list is not None:
                if not col_list:
                    return None
                s = series_or_df[col_list[0]]
            else:
                s = series_or_df
            v = s.dropna()
            return float(v.iloc[-1]) if not v.empty else None

        return {
            "macd": last_val(macd_df, macd_col),
            "macd_signal": last_val(macd_df, sig_col),
            "macd_hist": last_val(macd_df, hist_col),
            "rsi": last_val(rsi_series),
            "pivot": pivot,
            "r1": r1,
            "s1": s1,
            "r2": r2,
            "s2": s2,
        }
    except Exception:
        return null_result
