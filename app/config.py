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
        default=["gemini", "groq", "openrouter"]
    )
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.5-flash")
    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="llama-3.3-70b-versatile")
    openrouter_api_key: str = Field(default="")
    openrouter_model: str = Field(default="meta-llama/llama-3.3-70b-instruct:free")

    # LLM daily budget guard (per provider)
    llm_daily_request_limit: int = Field(default=1400)

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
