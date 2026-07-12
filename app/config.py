from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Market
    assets: Annotated[list[str], NoDecode] = Field(default=["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    timeframe: str = Field(default="1h")
    # Asset class per symbol — format: "BTC/USDT:crypto,AAPL:stock"
    asset_classes: Annotated[list[str], NoDecode] = Field(default=[])

    # Broker
    broker: Literal["paper", "hyperliquid_testnet"] = Field(default="paper")
    paper_initial_balance: float = Field(default=10_000.0)
    paper_fee_pct: float = Field(default=0.001)
    paper_slippage_pct: float = Field(default=0.0005)

    # LLM gateway — ordered list of providers to try
    llm_provider_order: Annotated[list[str], NoDecode] = Field(
        default=["groq", "gemini", "openrouter"]
    )
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.5-flash")
    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    openrouter_api_key: str = Field(default="")
    openrouter_model: str = Field(default="nvidia/nemotron-3-ultra-550b-a55b:free")

    # LLM daily budget guard (per provider)
    llm_daily_request_limit: int = Field(default=1400)

    # Per-provider pacing (requests/minute, free-tier friendly). 0 disables pacing.
    gemini_rpm: float = Field(default=15.0)
    groq_rpm: float = Field(default=30.0)
    openrouter_rpm: float = Field(default=20.0)
    # 429 handling: cooldown when Retry-After is absent, retry passes when all
    # providers are cooling down, cap on a single backoff wait.
    llm_max_retries: int = Field(default=3)
    llm_cooldown_seconds: float = Field(default=60.0)
    llm_max_backoff_wait: float = Field(default=45.0)

    # Persistence
    database_url: str = Field(default="sqlite:///./paper_trading.db")

    # Risk limits
    max_position_pct: float = Field(default=0.20)   # max 20% equity per asset
    max_total_exposure_pct: float = Field(default=0.80)
    max_open_positions: int = Field(default=5)
    default_sl_pct: float = Field(default=0.03)     # 3% stop loss
    default_tp_pct: float = Field(default=0.06)     # 6% take profit
    max_daily_drawdown_pct: float = Field(default=0.05)  # kill-switch at 5%
    max_holding_hours: int = Field(default=48)           # time-based exit

    # Trend filter (regime gate)
    trend_filter_enabled: bool = Field(default=True)
    trend_ema_period: int = Field(default=50)

    # Cooldown after a stop-loss before re-opening the same asset
    cooldown_hours_after_stop: int = Field(default=6)

    # Sentiment agent: only act on extreme Fear & Greed readings
    sentiment_extreme_only: bool = Field(default=True)
    sentiment_extreme_threshold: int = Field(default=25)

    # Reflection: distil lessons after every N closed trades
    reflection_every_n_trades: int = Field(default=5)

    # Backtest: refit the (slow) Prophet forecast at most every N bars and reuse
    # the value in between. Live trading is unaffected (one fit per hourly cycle).
    forecast_refit_every: int = Field(default=24)

    # Bull vs Bear debate before PM aggregation (default OFF, backward compatible).
    # Live: LLM bull/bear argue, PM judges transcript + weighted vote.
    # Backtest (deterministic): proxy penalises conviction on high agent disagreement.
    debate_enabled: bool = Field(default=True)
    debate_rounds: int = Field(default=1)          # 1-2 rounds bull+bear
    debate_max_penalty: float = Field(default=0.5)  # max conviction cut at full split
    # Run the LLM debate only when the weighted signal score is borderline
    # (|score| within [low, high]); saves LLM calls on clear-cut setups.
    debate_only_when_borderline: bool = Field(default=False)
    debate_borderline_low: float = Field(default=0.05)
    debate_borderline_high: float = Field(default=0.35)

    # Regime-adaptive agent weights (default OFF, backward compatible).
    # High volatility → shift weight from technical to sentiment/news; calm → reverse.
    adaptive_weights_enabled: bool = Field(default=True)
    adaptive_vol_lookback: int = Field(default=24)      # bars for realized vol
    adaptive_vol_low_pct: float = Field(default=0.004)  # per-bar return std, calm below
    adaptive_vol_high_pct: float = Field(default=0.009)  # per-bar return std, high above
    adaptive_shift: float = Field(default=0.35)         # multiplicative tilt (0..1)

    # Agent weights for PortfolioManager (must sum to 1.0)
    agent_weights: dict = Field(
        default={
            "technical": 0.35,
            "forecast": 0.20,
            "sentiment": 0.20,
            "onchain": 0.15,
            "news": 0.10,
        }
    )

    # Whale Alert
    whale_alert_api_key: str = Field(default="")

    # CryptoPanic
    cryptopanic_api_key: str = Field(default="")

    @field_validator("database_url", mode="before")
    @classmethod
    def _default_db(cls, v: object) -> object:
        """Empty DATABASE_URL falls back to a local SQLite file (dev mode)."""
        if v is None or (isinstance(v, str) and not v.strip()):
            return "sqlite:///./paper_trading.db"
        return v

    @field_validator("assets", "llm_provider_order", "asset_classes", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        """Accept comma-separated env values (e.g. BTC/USDT,ETH/USDT) or JSON lists."""
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json

                return json.loads(s)
            return [item.strip() for item in s.split(",") if item.strip()]
        return v


settings = Settings()
