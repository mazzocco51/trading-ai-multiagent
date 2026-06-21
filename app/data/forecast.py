from __future__ import annotations

import pandas as pd


def get_forecast(asset: str, timeframe: str, ohlcv_df: pd.DataFrame) -> dict:
    null_result = {
        "expected_move_pct": None,
        "direction": None,
        "confidence": 0.0,
        "mae": None,
        "degraded": True,
    }
    if ohlcv_df is None or ohlcv_df.empty or len(ohlcv_df) < 30:
        return null_result

    try:
        from prophet import Prophet

        df_prophet = ohlcv_df["close"].reset_index()
        df_prophet.columns = ["ds", "y"]
        df_prophet["ds"] = df_prophet["ds"].dt.tz_localize(None)

        split = int(len(df_prophet) * 0.85)
        train, test = df_prophet.iloc[:split], df_prophet.iloc[split:]

        m = Prophet(daily_seasonality=False, weekly_seasonality=True, yearly_seasonality=False)
        m.fit(train)

        future = m.make_future_dataframe(periods=len(test) + 1, freq="h")
        forecast = m.predict(future)

        # MAE on test set
        test_preds = forecast.set_index("ds").loc[test["ds"], "yhat"]
        mae = float((test["y"].values - test_preds.values).__abs__().mean()) if len(test_preds) == len(test) else None

        last_close = float(df_prophet["y"].iloc[-1])
        next_pred = float(forecast["yhat"].iloc[-1])
        move_pct = (next_pred - last_close) / last_close

        return {
            "expected_move_pct": round(move_pct, 6),
            "direction": "up" if move_pct > 0 else "down",
            "confidence": 0.6 if mae is None else max(0.1, min(0.9, 1 - abs(mae) / (last_close + 1e-9))),
            "mae": mae,
            "degraded": False,
        }
    except Exception:
        return null_result
