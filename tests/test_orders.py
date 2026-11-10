from datetime import timedelta

import pytest

from helpers import NOW, make_intent, make_quote
from optplat.broker import BrokerAdapter, SimBroker
from optplat.models import BrokerOrderStatus, Mode, OrderState, OrderIntent
from optplat.orders import InvalidTransition, LiveTradingDisabled, OrderManager
from optplat.store import Store


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
    manager = OrderManager(broker, Store(":memory:"), clock=clock)
    return manager, broker, clock


def test_approved_order_fills(env):
    manager, broker, _ = env
    order = manager.submit_buy(make_intent())
    assert order.state is OrderState.FILLED
    assert order.filled_qty == 4 and order.avg_fill_price == 2.01
    assert [h["state"] for h in order.history] == ["DRAFT", "RISK_APPROVED", "SUBMITTED", "FILLED"]
    assert len(broker.get_positions()) == 1


def test_risk_rejection_never_reaches_the_broker(env):
    manager, broker, _ = env
    order = manager.submit_buy(make_intent(qty=50))
    assert order.state is OrderState.RISK_REJECTED
    assert order.risk_failures
    assert broker._orders == {}


def test_resubmitting_same_key_returns_same_order(env):
    manager, broker, _ = env
    first = manager.submit_buy(make_intent())
    second = manager.submit_buy(make_intent())
    assert first.id == second.id
    assert len(broker._orders) == 1


def test_same_key_with_different_details_is_refused(env):
    manager, _, _ = env
    manager.submit_buy(make_intent())
    with pytest.raises(ValueError):
        manager.submit_buy(make_intent(qty=2))


def test_kill_switch_blocks_new_orders(env):
    manager, broker, _ = env
    manager.set_kill_switch(True, "test")
    order = manager.submit_buy(make_intent())
    assert order.state is OrderState.RISK_REJECTED
    assert "Kill switch is active" in order.risk_failures
    manager.set_kill_switch(False)
    assert manager.submit_buy(make_intent("key-00000002")).state is OrderState.FILLED


def test_missing_quote_rejects_without_calling_broker(env):
    manager, broker, _ = env
    broker._quotes.clear()
    order = manager.submit_buy(make_intent())
    assert order.state is OrderState.RISK_REJECTED
    assert broker._orders == {}


def test_live_adapter_is_refused():
    class LiveBroker(SimBroker):
        mode = Mode.LIVE

    manager = OrderManager(LiveBroker(), Store(":memory:"), clock=Clock())
    with pytest.raises(LiveTradingDisabled):
        manager.submit_buy(make_intent())


def test_resting_order_can_be_cancelled(env):
    manager, broker, _ = env
    order = manager.submit_buy(make_intent(limit=2.00))  # below ask+slippage: rests
    assert order.state is OrderState.SUBMITTED
    cancelled = manager.cancel(order.id)
    assert cancelled.state is OrderState.CANCELLED


def test_filled_order_cannot_be_cancelled(env):
    manager, _, _ = env
    order = manager.submit_buy(make_intent())
    with pytest.raises(InvalidTransition):
        manager.cancel(order.id)


def test_unknown_submit_error_requires_reconcile_and_then_resolves(env):
    manager, broker, clock = env

    real_submit = broker.submit_limit_order
    calls = {"n": 0}

    def flaky(intent: OrderIntent):
        calls["n"] += 1
        raise TimeoutError("socket timed out")

    broker.submit_limit_order = flaky
    order = manager.submit_buy(make_intent())
    assert order.state is OrderState.ERROR_RECONCILE_REQUIRED

    # Too soon: broker has no record, but we wait out the grace period before concluding anything.
    assert manager.reconcile() == []
    assert manager.get(order.id).state is OrderState.ERROR_RECONCILE_REQUIRED

    clock.now = NOW + timedelta(seconds=120)
    assert manager.reconcile() == [order.id]
    assert manager.get(order.id).state is OrderState.BROKER_REJECTED
    broker.submit_limit_order = real_submit


def test_reconcile_discovers_an_order_that_actually_went_through(env):
    manager, broker, clock = env
    real_submit = broker.submit_limit_order

    def placed_then_timeout(intent):
        real_submit(intent)  # the broker did receive and fill it
        raise TimeoutError("response lost")

    broker.submit_limit_order = placed_then_timeout
    order = manager.submit_buy(make_intent())
    assert order.state is OrderState.ERROR_RECONCILE_REQUIRED
    assert manager.reconcile() == [order.id]
    recovered = manager.get(order.id)
    assert recovered.state is OrderState.FILLED and recovered.broker_order_id.startswith("SIM-")


def test_inconsistent_broker_fill_is_flagged(env):
    manager, broker, _ = env
    broker.submit_limit_order = lambda intent: BrokerOrderStatus("X-1", intent.idempotency_key, "FILLED", 1, 2.0)
    order = manager.submit_buy(make_intent())  # quantity 4 but broker reports 1 filled
    assert order.state is OrderState.ERROR_RECONCILE_REQUIRED


def test_persistence_round_trip(env):
    manager, _, _ = env
    order = manager.submit_buy(make_intent())
    loaded = manager.get(order.id)
    assert loaded.to_dict() == order.to_dict()
    kinds = [e["kind"] for e in manager.store.audit_events(order.id)]
    assert kinds[0] == "order_created" and kinds.count("order_state") == 3


def test_every_state_has_a_transition_entry():
    from optplat.orders import TRANSITIONS

    assert set(TRANSITIONS) == set(OrderState)
