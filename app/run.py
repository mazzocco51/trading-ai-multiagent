"""Run a single trading cycle (or loop with --loop flag)."""
from __future__ import annotations

import argparse
import logging
import time

from sqlalchemy.orm import sessionmaker

from app.broker.paper import PaperBroker
from app.config import settings
from app.llm.gateway import LLMGateway
from app.llm.providers.gemini import GeminiProvider
from app.llm.providers.groq import GroqProvider
from app.llm.providers.openrouter import OpenRouterProvider
from app.orchestrator import run_cycle
from app.persistence.models import init_db
from app.persistence.repo import load_broker_state, save_broker_state


def build_gateway() -> LLMGateway:
    providers = []
    for name in settings.llm_provider_order:
        if name == "gemini" and settings.gemini_api_key:
            providers.append(GeminiProvider(settings.gemini_api_key, settings.gemini_model))
        elif name == "groq" and settings.groq_api_key:
            providers.append(GroqProvider(settings.groq_api_key, settings.groq_model))
        elif name == "openrouter" and settings.openrouter_api_key:
            providers.append(
                OpenRouterProvider(settings.openrouter_api_key, settings.openrouter_model)
            )
    return LLMGateway(providers, daily_limit=settings.llm_daily_request_limit)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Quiet noisy third-party loggers so the plain-Italian explanation stands out.
    for noisy in ("httpx", "cmdstanpy", "prophet", "prophet.plot"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument(
        "--interval",
        type=int,
        default=3600,
        help="Seconds between cycles (default 3600)",
    )
    args = parser.parse_args()

    engine = init_db(settings.database_url)
    SessionFactory = sessionmaker(bind=engine)
    broker = PaperBroker(
        settings.paper_initial_balance,
        settings.paper_fee_pct,
        settings.paper_slippage_pct,
    )
    gateway = build_gateway()

    _log = logging.getLogger(__name__)

    # Restore balance + open positions from a previous run (perpetual cron).
    with SessionFactory() as session:
        state = load_broker_state(session)
        if state:
            broker.load_state(state)
            _log.info("Restored broker state: balance=%.2f", broker.get_balance())

    while True:
        with SessionFactory() as session:
            results = run_cycle(settings, broker, gateway, session)
            save_broker_state(session, broker.export_state())
            session.commit()

        for r in results:
            _log.info(
                "Asset=%s action=%s veto=%s balance=%.2f",
                r["asset"],
                r["action"],
                r["veto"],
                r["balance"],
            )

        if not args.loop:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
