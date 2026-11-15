from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from helpers import CONTRACT, NOW, make_intent
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.evaluation import closed_trade_pnl, summarize_closed_trades
from optplat.models import Order, OrderState, Side
from optplat.orders import OrderManager
from optplat.store import Store


def sell(i, fill, basis, qty=1, state=OrderState.FILLED):
    o = Order.new(make_intent(f"sell-key-{i:05d}", qty=qty, side=Side.SELL_TO_CLOSE), NOW + timedelta(minutes=i))
    o.state, o.avg_fill_price, o.cost_basis, o.filled_qty = state, fill, basis, qty
    o.updated_at = NOW + timedelta(minutes=i)
    return o


def test_no_trades_has_no_fabricated_win_rate():
    s = summarize_closed_trades([])
    assert s["status"] == "NO_CLOSED_TRADES"
    assert s["win_rate_pct"] is None and s["average_pnl_usd"] is None and s["closed_trade_max_drawdown_pct"] is None
    assert s["limitations"]


def test_pnl_uses_multiplier_and_ignores_unfilled_or_unpriced():
    assert closed_trade_pnl(sell(1, 3.0, 2.0, qty=2)) == pytest.approx(200.0)
    assert closed_trade_pnl(sell(1, 3.0, 2.0, state=OrderState.CANCELLED)) is None
    assert closed_trade_pnl(sell(1, 3.0, None)) is None
    buy = Order.new(make_intent("buy-key-00001"), NOW)
    assert closed_trade_pnl(buy) is None
    s = summarize_closed_trades([sell(1, 3.0, None), buy])
    assert s["closed_trades"] == 0 and s["unpriced_exits"] == 1


def test_small_sample_is_not_called_a_result():
    s = summarize_closed_trades([sell(i, 3.0, 2.0) for i in range(5)])
    assert s["status"] == "INSUFFICIENT_SAMPLE" and s["win_rate_pct"] == 100.0
    big = summarize_closed_trades([sell(i, 3.0, 2.0) for i in range(30)])
    assert big["status"] == "SAMPLE_SIZE_MET_NOT_PROOF_OF_EDGE"


def test_concentration_and_drawdown():
    orders = [sell(1, 12.0, 2.0), sell(2, 1.0, 2.0), sell(3, 1.0, 2.0)]  # +1000, -100, -100
    s = summarize_closed_trades(orders, starting_equity=10_000)
    assert s["realized_pnl_usd"] == 800.0
    assert s["pnl_without_best_trade_usd"] == -200.0
    assert s["best_trade_share_of_gross_wins_pct"] == 100.0
    assert s["profit_factor"] == 5.0
    assert s["closed_trade_max_drawdown_pct"] == pytest.approx(200 / 11000 * 100, abs=0.001)


def test_order_of_input_does_not_change_drawdown():
    a = [sell(1, 1.0, 2.0), sell(2, 12.0, 2.0)]
    assert summarize_closed_trades(a, starting_equity=1000) == summarize_closed_trades(a[::-1], starting_equity=1000)


def test_results_endpoint_requires_token_and_works():
    c = TestClient(create_app(OrderManager(SimBroker(), Store(":memory:")), "t" * 24))
    assert c.get("/api/results").status_code == 401
    body = c.get("/api/results", headers={"X-API-Token": "t" * 24}).json()
    assert body["status"] == "NO_CLOSED_TRADES"
