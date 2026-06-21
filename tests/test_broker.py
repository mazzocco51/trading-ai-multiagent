from __future__ import annotations

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
