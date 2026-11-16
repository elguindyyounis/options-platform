from datetime import timedelta

from helpers import CONTRACT, NOW, make_intent, make_quote
from optplat.broker import SimBroker
from optplat.diagnostics import CLOCK_WARN_S, clock_status, describe_exc
from optplat.models import Side
from optplat.orders import OrderManager
from optplat.risk import RiskPolicy
from optplat.store import Store


def traded(tmp_path, *, sell_all=False):
    store = Store(str(tmp_path / "t.db"))
    broker = SimBroker()
    broker.set_quote(make_quote())
    manager = OrderManager(broker, store, RiskPolicy(), clock=lambda: NOW)
    manager.submit(make_intent("buy-00000001", qty=4, limit=2.02))
    if sell_all:
        manager.submit(make_intent("sell-0000001", qty=4, limit=1.88, side=Side.SELL_TO_CLOSE))
    return store, broker


def test_a_restart_gets_its_open_position_and_cash_back(tmp_path):
    store, before = traded(tmp_path)
    assert before.get_positions() and before.cash < 100_000
    fresh = SimBroker()
    assert fresh.get_positions() == [] and fresh.cash == 100_000  # what used to happen on every restart
    info = fresh.restore(store.list_orders(limit=1000))
    assert info["warnings"] == [] and info["orders_replayed"] == 1 and info["open_positions"] == 1
    assert [(p.contract, p.quantity) for p in fresh.get_positions()] == [(p.contract, p.quantity) for p in before.get_positions()]
    assert abs(fresh.cash - before.cash) < 0.01
    assert fresh.find_order_by_client_id("buy-00000001").filled_qty == 4  # a retried order is not sent twice


def test_a_closed_position_stays_closed_and_the_realised_result_is_kept(tmp_path):
    store, before = traded(tmp_path, sell_all=True)
    assert before.get_positions() == []
    fresh = SimBroker()
    info = fresh.restore(store.list_orders(limit=1000))
    assert info["open_positions"] == 0 and info["warnings"] == []
    assert abs(fresh.cash - before.cash) < 0.01 and fresh.cash != 100_000  # the spread and slippage are not erased


def test_new_orders_after_a_restore_get_fresh_broker_ids(tmp_path):
    store, _ = traded(tmp_path)
    fresh = SimBroker()
    fresh.restore(store.list_orders(limit=1000))
    fresh.set_quote(make_quote())
    status = fresh.submit_limit_order(make_intent("buy-00000002", qty=1, limit=2.02))
    assert status.broker_order_id == "SIM-000002"


def test_an_impossible_history_is_reported_and_skipped_not_guessed(tmp_path):
    store, _ = traded(tmp_path)
    orders = store.list_orders(limit=1000)
    sell_first = [o for o in orders]
    bad = SimBroker()
    broker = SimBroker()
    broker.set_quote(make_quote())
    manager = OrderManager(broker, Store(str(tmp_path / "x.db")), RiskPolicy(), clock=lambda: NOW)
    manager.submit(make_intent("buy-00000009", qty=2, limit=2.02))
    sold = manager.submit(make_intent("sell-0000009", qty=2, limit=1.88, side=Side.SELL_TO_CLOSE))
    only_the_sell = [sold]
    info = bad.restore(only_the_sell)
    assert info["orders_replayed"] == 0 and any("only 0 are held" in w for w in info["warnings"])
    assert bad.cash == 100_000 and sell_first


def test_orders_that_never_filled_are_not_replayed(tmp_path):
    store = Store(str(tmp_path / "n.db"))
    broker = SimBroker()
    broker.set_quote(make_quote())
    manager = OrderManager(broker, store, RiskPolicy(), clock=lambda: NOW)
    manager.submit(make_intent("buy-00000003", qty=4, limit=1.00))  # limit below the ask: rests unfilled
    fresh = SimBroker()
    info = fresh.restore(store.list_orders(limit=1000))
    assert info["orders_replayed"] == 0 and fresh.cash == 100_000


def test_describe_exc_names_the_message_and_the_line_inside_this_package():
    from optplat.risk import RiskPolicy as RP  # noqa: F401

    def boom():
        raise AttributeError("'NoneType' object has no attribute 'strike'")
    try:
        boom()
    except AttributeError as exc:
        text = describe_exc(exc)
    assert text.startswith("AttributeError: 'NoneType' object has no attribute 'strike'")
    assert len(describe_exc(ValueError("x" * 500))) < 260


def test_clock_status_warns_before_the_gate_rejects_and_says_how_to_fix_it():
    assert clock_status(None, 5)["warning"] is None
    assert clock_status(-30.0, 5)["behind_s"] == 0.0 and clock_status(-30.0, 5)["warning"] is None  # clock ahead is not this problem
    assert clock_status(CLOCK_WARN_S - 0.5, 5)["warning"] is None
    near = clock_status(4.0, 5)["warning"]
    assert near and "close to the 5s limit" in near
    late = clock_status(9.0, 5)
    assert late["behind_s"] == 9.0 and "being rejected" in late["warning"] and "Set time and date automatically" in late["warning"]
