"""Generate a static, self-contained HTML dashboard from the database.

Reads equity history + broker state (open positions, closed trades) and injects
them into dashboard/template.html, producing public/index.html. The page fetches
live prices client-side from Binance, so it works as a plain static file
(local preview or GitHub Pages).

Run:  python dashboard/build_html.py
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.persistence.models import init_db
from app.persistence.repo import (
    get_equity_history,
    get_recent_decisions,
    load_broker_state,
)

HERE = Path(__file__).parent
TEMPLATE = HERE / "template.html"
OUT_DIR = HERE.parent / "public"
OUT = OUT_DIR / "index.html"


def build() -> Path:
    engine = init_db(settings.database_url)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        state = load_broker_state(session) or {}
        equity_rows = get_equity_history(session, 500)
        decisions = get_recent_decisions(session, 30)

    balance = float(state.get("balance", settings.paper_initial_balance))
    positions = list((state.get("positions") or {}).values())
    deployed = sum(p["size"] * p["entry_price"] for p in positions)

    data = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "assets": list(settings.assets),
        "initial_balance": settings.paper_initial_balance,
        "balance": balance,
        "equity": balance + deployed,
        "open_positions": positions,
        "closed_trades": state.get("trade_history", []),
        "decisions": decisions,
        # repo returns newest-first; reverse to chronological for the chart
        "equity_history": [
            {"t": r["timestamp"], "balance": r["balance"]} for r in reversed(equity_rows)
        ],
    }

    html = TEMPLATE.read_text(encoding="utf-8").replace("__DATA_JSON__", json.dumps(data))
    OUT_DIR.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    out = build()
    print(f"Dashboard written to {out}")
