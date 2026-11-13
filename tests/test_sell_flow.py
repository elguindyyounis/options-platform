from datetime import date, timedelta

import pytest

from helpers import CONTRACT, NOW, make_intent, make_quote
from optplat.broker import SimBroker
from optplat.models import Account, OptionContract, OrderState, Position, Right, Side
from optplat.orders import OrderManager
from optplat.pricing import sell_limit_for
from optplat.risk import RiskPolicy, evaluate
from optplat.store import Store

POLICY = RiskPolicy()
ACCOUNT = Account(equity=100_000, cash=100_000, open_premium=0)
HELD = [Position(CONTRACT, 4, 2.0)]


def sell(qty=4, limit=1.88, key="sell-00000001"):
    return make_intent(key, qty=qty, limit=limit, side=Side.SELL_TO_CLOSE)


def risk(intent=None, quote="default", positions=HELD, kill=False, pending=0):
    if quote == "default":
        quote = make_quote()
    return evaluate(intent or sell(), quote, ACCOUNT, positions, POLICY, now=NOW, kill_switch=kill, pending_close_qty=pending)


# ---------------------------------------------------------------- risk (sell side)
def test_good_sell_is_allowed():
    assert risk().allowed


def test_kill_switch_never_blocks_a_close():
    assert risk(kill=True).allowed


def test_cannot_sell_without_a_position():
    d = risk(positions=[])
    assert any("Not enough open position" in f for f in d.failures)


def test_cannot_sell_more_than_held_or_already_closing():
    assert not risk(intent=sell(qty=5)).allowed
    assert not risk(intent=sell(qty=1), pending=4).allowed
    assert risk(intent=sell(qty=1), pending=3).allowed


def test_zero_bid_is_unobservable():
    assert any("Zero bid" in f for f in risk(quote=make_quote(0.0, 0.10)).failures)


def test_limit_may_not_dump_far_below_the_bid():
    assert any("undercuts the bid" in f for f in risk(intent=sell(limit=1.00)).failures)
    assert risk(intent=sell(limit=1.85)).allowed


def test_stale_or_unverified_quotes_block_sells_too():
    assert not risk(quote=make_quote(as_of=NOW - timedelta(seconds=300))).allowed
    assert not risk(quote=make_quote(verified=False)).allowed


def test_expired_contract_cannot_be_sold():
    gone = OptionContract("SPY", NOW.date() - timedelta(days=1), Right.CALL, 600.0)
    d = risk(intent=make_intent("sell-00000009", contract=gone, side=Side.SELL_TO_CLOSE, limit=1.88),
             quote=make_quote(contract=gone), positions=[Position(gone, 4, 2.0)])
    assert "Contract has expired" in d.failures


def test_wide_spread_is_a_warning_not_a_blocker_for_exits():
    d = risk(quote=make_quote(1.00, 2.00), intent=sell(limit=1.00))
    assert d.allowed and d.warnings


# ---------------------------------------------------------------- order manager
class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def env():
    clock = Clock()
    broker = SimBroker()
    broker.set_quote(make_quote())
    return OrderManager(broker, Store(":memory:"), clock=clock), broker, clock


def test_round_trip_records_cost_basis_and_realized_pnl(env):
    manager, broker, _ = env
    buy = manager.submit(make_intent())
    assert buy.state is OrderState.FILLED and buy.avg_fill_price == 2.01
    broker.set_quote(make_quote(2.90, 3.00))
    order = manager.submit(sell(limit=sell_limit_for(2.90)))
    assert order.state is OrderState.FILLED
    assert order.cost_basis == 2.01 and order.avg_fill_price == 2.89
    assert broker.get_positions() == []
    report = manager.report()
    assert report["closed_trades"] == 1 and report["wins"] == 1
    assert report["sample_verdict"] == "INSUFFICIENT_SAMPLE" and report["win_rate_ci95_pct"][1] == 100.0
    assert report["realized_pnl"] == round((2.89 - 2.01) * 4 * 100, 2)
    assert manager.get(order.id).cost_basis == 2.01  # survives persistence


def test_selling_nothing_is_risk_rejected(env):
    manager, broker, _ = env
    order = manager.submit(sell())
    assert order.state is OrderState.RISK_REJECTED
    assert broker._orders == {}


def test_working_sell_blocks_a_second_sell_of_the_same_shares(env):
    manager, broker, _ = env
    manager.submit(make_intent())
    broker.set_quote(make_quote(2.90, 3.00))
    resting = manager.submit(sell(qty=4, limit=3.50))  # limit above what the sim pays: rests
    assert resting.state is OrderState.SUBMITTED
    second = manager.submit(sell(qty=1, limit=2.85, key="sell-00000002"))
    assert second.state is OrderState.RISK_REJECTED
    assert any("already being closed" in f for f in second.risk_failures)


def test_kill_switch_blocks_buys_but_not_sells(env):
    manager, broker, _ = env
    manager.submit(make_intent())
    broker.set_quote(make_quote(2.90, 3.00))
    manager.set_kill_switch(True)
    assert manager.submit(make_intent("key-00000002", qty=1)).state is OrderState.RISK_REJECTED
    assert manager.submit(sell(limit=sell_limit_for(2.90))).state is OrderState.FILLED


def test_entry_and_close_times(env):
    manager, broker, clock = env
    assert manager.entry_time(CONTRACT) is None and manager.last_close_time(CONTRACT) is None
    manager.submit(make_intent())
    assert manager.entry_time(CONTRACT) == NOW
    clock.now = NOW + timedelta(hours=2)
    broker.set_quote(make_quote(2.90, 3.00, as_of=clock.now))
    manager.submit(sell(limit=sell_limit_for(2.90)))
    assert manager.last_close_time(CONTRACT) == NOW + timedelta(hours=2)


def test_report_marks_open_positions_at_the_bid(env):
    manager, broker, _ = env
    manager.submit(make_intent())
    broker.set_quote(make_quote(2.51, 2.60))
    row = manager.report()["open"][0]
    assert row["mark"] == 2.51 and row["mark_quality"] == "BID"
    assert row["unrealized_pnl"] == round((2.51 - 2.01) * 4 * 100, 2)
    broker._quotes.clear()
    row = manager.report()["open"][0]
    assert row["mark"] is None and row["mark_quality"] == "UNOBSERVABLE"


def test_side_survives_persistence(env):
    manager, _, _ = env
    order = manager.submit(sell())
    assert manager.get(order.id).intent.side is Side.SELL_TO_CLOSE
