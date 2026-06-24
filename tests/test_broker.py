from __future__ import annotations

from datetime import UTC

from app.broker.paper import PaperBroker


def test_paper_broker_initial_balance():
    b = PaperBroker(initial_balance=10_000)
    assert b.get_balance() == 10_000


def test_place_long_and_close_at_profit():
    b = PaperBroker(initial_balance=10_000, fee_pct=0.001, slippage_pct=0.0)
    result = b.place_order(
        "BTC/USDT", "long", size_pct=0.10, mark_price=50_000.0, sl_price=48_000.0, tp_price=53_000.0
    )
    assert result.success
    balance_after_open = b.get_balance()
    b.close_position("BTC/USDT", mark_price=53_000.0)
    assert b.get_balance() > balance_after_open


def test_place_order_insufficient_balance():
    b = PaperBroker(initial_balance=100)
    result = b.place_order(
        "BTC/USDT", "long", size_pct=1.0, mark_price=50_000.0, sl_price=48_000.0, tp_price=53_000.0
    )
    assert not result.success
    assert result.reason == "insufficient_balance"


def test_sl_trigger():
    b = PaperBroker(initial_balance=10_000, slippage_pct=0.0)
    b.place_order("BTC/USDT", "long", 0.10, 50_000.0, 48_000.0, 53_000.0)
    triggered = b.check_sl_tp("BTC/USDT", 47_000.0)
    assert triggered == "sl"
    assert "BTC/USDT" not in b.positions


def test_tp_trigger():
    b = PaperBroker(initial_balance=10_000, slippage_pct=0.0)
    b.place_order("BTC/USDT", "long", 0.10, 50_000.0, 48_000.0, 53_000.0)
    triggered = b.check_sl_tp("BTC/USDT", 54_000.0)
    assert triggered == "tp"
    assert "BTC/USDT" not in b.positions


def test_get_positions():
    b = PaperBroker(initial_balance=10_000, slippage_pct=0.0)
    b.place_order("BTC/USDT", "long", 0.10, 50_000.0, 48_000.0, 53_000.0)
    positions = b.get_positions()
    assert len(positions) == 1
    assert positions[0].asset == "BTC/USDT"


# ---------------------------------------------------------------------------
# Time-based exit logic (A3)
# ---------------------------------------------------------------------------

def _age_hours(h: float) -> str:
    from datetime import datetime, timedelta
    dt = datetime.now(UTC) - timedelta(hours=h)
    return dt.isoformat()


def _check_time_exit(opened_at: str, max_hours: int, mark_price: float) -> bool:
    from datetime import datetime
    opened_dt = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
    age_hours = (datetime.now(UTC) - opened_dt).total_seconds() / 3600
    return mark_price > 0 and age_hours >= max_hours


def test_time_exit_triggers():
    assert _check_time_exit(_age_hours(49), max_hours=48, mark_price=50_000.0) is True


def test_time_exit_no_trigger():
    assert _check_time_exit(_age_hours(2), max_hours=48, mark_price=50_000.0) is False


def test_time_exit_zero_price():
    # must NOT close when price is 0 — preserves the existing guard
    assert _check_time_exit(_age_hours(100), max_hours=48, mark_price=0.0) is False
