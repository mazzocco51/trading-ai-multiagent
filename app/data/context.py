from __future__ import annotations

from pydantic import BaseModel

from app.data.forecast import get_forecast
from app.data.indicators import compute_indicators
from app.data.news import get_news_headlines
from app.data.prices import get_ohlcv
from app.data.sentiment import get_fear_and_greed
from app.data.whale import get_whale_events


class MarketContext(BaseModel):
    asset: str
    timeframe: str
    ohlcv: list[dict] = []
    indicators: dict = {}
    forecast: dict = {}
    fear_and_greed: dict = {}
    whale_events: list = []
    news_headlines: list = []
    degraded_sources: list[str] = []

    model_config = {"arbitrary_types_allowed": True}


def build_context(asset: str, timeframe: str, whale_api_key: str = "") -> MarketContext:
    ctx = MarketContext(asset=asset, timeframe=timeframe)

    try:
        df = get_ohlcv(asset, timeframe)
        ctx.ohlcv = df.reset_index().to_dict("records") if not df.empty else []
        if df.empty:
            ctx.degraded_sources.append("prices")
    except Exception:
        ctx.degraded_sources.append("prices")
        df = None  # type: ignore[assignment]

    try:
        import pandas as pd

        df_for_ind = (
            pd.DataFrame(ctx.ohlcv).set_index("timestamp") if ctx.ohlcv else pd.DataFrame()
        )
        ctx.indicators = compute_indicators(df_for_ind)
    except Exception:
        ctx.degraded_sources.append("indicators")

    try:
        import pandas as pd

        df_for_fc = (
            pd.DataFrame(ctx.ohlcv).set_index("timestamp") if ctx.ohlcv else pd.DataFrame()
        )
        ctx.forecast = get_forecast(asset, timeframe, df_for_fc)
        if ctx.forecast.get("degraded"):
            ctx.degraded_sources.append("forecast")
    except Exception:
        ctx.forecast = {"degraded": True}
        ctx.degraded_sources.append("forecast")

    try:
        fng = get_fear_and_greed()
        ctx.fear_and_greed = fng
        if fng.get("degraded"):
            ctx.degraded_sources.append("fear_and_greed")
    except Exception:
        ctx.degraded_sources.append("fear_and_greed")

    try:
        ctx.whale_events = get_whale_events(whale_api_key)
    except Exception:
        ctx.degraded_sources.append("whale")

    try:
        ctx.news_headlines = get_news_headlines(asset)
    except Exception:
        ctx.degraded_sources.append("news")

    return ctx
