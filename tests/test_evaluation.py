from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from helpers import CONTRACT, NOW, make_intent
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.evaluation import closed_trade_pnl, split_half_check, summarize_closed_trades
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


# ---- open-position marks (challenge 4) ----
from helpers import make_quote  # noqa: E402
from optplat.broker.base import QuoteUnavailable  # noqa: E402
from optplat.evaluation import summarize_open_positions  # noqa: E402
from optplat.models import Position  # noqa: E402


def _marks(quote_or_exc, **kw):
    def get_quote(_c):
        if isinstance(quote_or_exc, Exception):
            raise quote_or_exc
        return quote_or_exc
    return summarize_open_positions([Position(CONTRACT, 2, 2.0)], get_quote, NOW, **kw)


def test_open_position_marked_to_bid_not_mid_or_ask():
    s = _marks(make_quote(bid=1.50, ask=2.50))
    assert s["unrealized_pnl_usd"] == pytest.approx(-100.0)  # (1.50-2.00)*2*100
    assert s["marked"][0]["bid"] == 1.50 and not s["unmarked"]


def test_unmarkable_positions_make_total_null_never_zero():
    for q, why in [
        (QuoteUnavailable("x"), "no_quote"),
        (RuntimeError("boom"), "quote_error"),
        (make_quote(verified=False), "quote_time_unverified"),
        (make_quote(as_of=NOW - timedelta(hours=1)), "stale_quote"),
        (make_quote(bid=3.0, ask=2.0), "invalid_quote"),
    ]:
        s = _marks(q)
        assert s["unrealized_pnl_usd"] is None and s["unmarked"][0]["reason"] == why


def test_partial_marks_do_not_hide_unmarked_losses():
    other = CONTRACT.__class__("QQQ", CONTRACT.expiry, CONTRACT.right, 500.0)
    def gq(c):
        if c == CONTRACT:
            return make_quote(bid=3.0, ask=3.1)
        raise QuoteUnavailable("none")
    s = summarize_open_positions([Position(CONTRACT, 1, 2.0), Position(other, 1, 2.0)], gq, NOW)
    assert s["unrealized_pnl_usd"] is None and len(s["marked"]) == 1 and len(s["unmarked"]) == 1


def test_no_positions_is_zero_and_results_endpoint_includes_section():
    assert summarize_open_positions([], lambda c: None, NOW)["unrealized_pnl_usd"] == 0.0
    c = TestClient(create_app(OrderManager(SimBroker(), Store(":memory:")), "t" * 24))
    body = c.get("/api/results", headers={"X-API-Token": "t" * 24}).json()
    assert body["open_positions"]["unrealized_pnl_usd"] == 0.0


def test_split_half_withheld_below_min_trades():
    r = split_half_check([5.0] * 29)
    assert r["status"] == "INSUFFICIENT_SAMPLE" and r["consistent"] is None and r["first_half_pnl_usd"] is None
    assert summarize_closed_trades([sell(i, 3.0, 2.0) for i in range(5)])["split_half"]["consistent"] is None


def test_split_half_flags_unstable_and_stable_results():
    unstable = split_half_check([10.0] * 15 + [-4.0] * 15)
    assert unstable["status"] == "CHECKED" and unstable["consistent"] is False
    flip = split_half_check([10.0] * 15 + [-20.0] * 15)
    assert flip["first_half_pnl_usd"] == 150.0 and flip["second_half_pnl_usd"] == -300.0
    assert flip["consistent"] is False
    assert split_half_check([1.0] * 30)["consistent"] is True
    assert split_half_check([0.0] * 30)["consistent"] is False


def test_split_half_uses_time_order_in_summary():
    orders = [sell(i, 3.0, 2.0) for i in range(15)] + [sell(i, 1.0, 2.0) for i in range(15, 30)]
    s = summarize_closed_trades(list(reversed(orders)))
    assert s["split_half"]["first_half_pnl_usd"] > 0 > s["split_half"]["second_half_pnl_usd"]
    assert s["split_half"]["consistent"] is False


# ---- fill-model label (challenge 7) ----
def test_results_endpoint_names_the_fill_model_and_says_fees_are_not_modeled():
    c = TestClient(create_app(OrderManager(SimBroker(slippage_pct=0.5), Store(":memory:")), "t" * 24))
    fm = c.get("/api/results", headers={"X-API-Token": "t" * 24}).json()["fill_model"]
    assert fm["buys"] == "ask plus slippage" and fm["sells"] == "bid minus slippage"
    assert fm["slippage_pct"] == 0.5 and fm["commissions_modeled"] is False


def test_unknown_broker_fill_model_is_reported_unknown_not_conservative():
    from optplat.evaluation import describe_fill_model

    fm = describe_fill_model(object())
    assert fm["buys"] == "unknown" and fm["slippage_pct"] is None and fm["commissions_modeled"] is False
