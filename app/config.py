from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Market
    assets: List[str] = Field(default=["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    timeframe: str = Field(default="1h")

    # Broker
    broker: Literal["paper", "hyperliquid_testnet"] = Field(default="paper")
    paper_initial_balance: float = Field(default=10_000.0)
    paper_fee_pct: float = Field(default=0.001)
    paper_slippage_pct: float = Field(default=0.0005)

    # LLM gateway — ordered list of providers to try
    llm_provider_order: List[str] = Field(default=["gemini", "groq", "openrouter"])
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-2.0-flash")
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

    # Agent weights for PortfolioManager (must sum to 1.0)
    agent_weights: dict = Field(
        default={
            "technical": 0.30,
            "forecast": 0.20,
            "sentiment": 0.20,
            "onchain": 0.15,
            "news": 0.15,
        }
    )

    # Whale Alert
    whale_alert_api_key: str = Field(default="")

    # CryptoPanic
    cryptopanic_api_key: str = Field(default="")


settings = Settings()
