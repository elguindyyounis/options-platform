"""The IBKR paper mirror never changes the simulated account of record (synthetic fixtures only)."""
import pytest

from conformance import BrokerConformance
from helpers import CONTRACT, NOW, make_intent, make_quote
from optplat.broker import BrokerRejected
from optplat.broker.mirror import MirroredSimBroker
from optplat.broker.sim import SimBroker
from optplat.models import BrokerOrderStatus, Side
from optplat.orders import OrderManager
from optplat.risk import RiskPolicy
from optplat.store import Store


class RecordingMirror:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def healthcheck(self):
        raise AssertionError("the mirror's health must not be probed from a health check")

    def submit_limit_order(self, intent):
        self.calls.append(("submit", intent.idempotency_key, intent.side))
        if self.fail:
            raise self.fail
        return BrokerOrderStatus("ibkr:" + intent.idempotency_key, intent.idempotency_key, "FILLED", intent.quantity, 2.0)

    def cancel_order(self, broker_order_id):
        self.calls.append(("cancel", broker_order_id))
        return BrokerOrderStatus(broker_order_id, broker_order_id[5:], "CANCELLED", 0, None)


def mirrored(fail=None):
    m = RecordingMirror(fail)
    b = MirroredSimBroker(m, background=False)
    events = []
    b.attach_audit(lambda kind, oid, payload: events.append((kind, payload)))
    b.set_quote(make_quote(), )
    return b, m, events


class TestMirroredSimConformance(BrokerConformance):
    """It is still a conforming broker: the simulator answers every question."""

    def make_broker(self):
        return MirroredSimBroker(RecordingMirror(), background=False)

    def seed_quote(self, broker, bid, ask):
        broker.set_quote(make_quote(bid, ask))


def test_accepted_orders_and_cancels_are_copied_with_the_same_key():
    b, m, events = mirrored()
    b.submit_limit_order(make_intent(limit=2.50))
    resting = b.submit_limit_order(make_intent("key-rest", limit=1.00))
    b.cancel_order(resting.broker_order_id)
    assert m.calls == [("submit", "key-00000001", Side.BUY_TO_OPEN), ("submit", "key-rest", Side.BUY_TO_OPEN),
                       ("cancel", "ibkr:key-rest")]
    assert [k for k, _ in events] == ["ibkr_mirror_submitted", "ibkr_mirror_submitted", "ibkr_mirror_cancelled"]


def test_simulator_rejections_are_not_copied():
    b, m, _ = mirrored()
    with pytest.raises(BrokerRejected):
        b.submit_limit_order(make_intent("sell-x", side=Side.SELL_TO_CLOSE))
    assert m.calls == []


@pytest.mark.parametrize("fail", [BrokerRejected("too big"), ConnectionError("TWS closed")])
def test_mirror_failures_never_touch_the_simulated_account(fail):
    b, m, events = mirrored(fail)
    plain = SimBroker()
    plain.set_quote(make_quote())
    s1, s2 = b.submit_limit_order(make_intent(limit=2.50)), plain.submit_limit_order(make_intent(limit=2.50))
    assert (s1.status, s1.filled_qty, s1.avg_fill_price) == (s2.status, s2.filled_qty, s2.avg_fill_price)
    assert b.get_account() == plain.get_account() and b.get_positions() == plain.get_positions()
    assert events[0][0] in ("ibkr_mirror_rejected", "ibkr_mirror_error")
    assert "TWS closed" not in str(events[0][1])  # only the error type is logged


def test_health_check_reports_the_last_outcome_without_calling_ibkr():
    b, _, _ = mirrored()
    b.submit_limit_order(make_intent(limit=2.50))
    h = b.healthcheck()
    assert h["connected"] is True and h["ibkr_mirror"]["state"] == "FILLED"


def test_background_worker_copies_in_order():
    m = RecordingMirror()
    b = MirroredSimBroker(m)
    b.set_quote(make_quote())
    b.submit_limit_order(make_intent("a", limit=2.50))
    b.submit_limit_order(make_intent("b", limit=2.50))
    b.submit_limit_order(make_intent("c", qty=4, limit=1.00, side=Side.SELL_TO_CLOSE))
    import time
    for _ in range(100):
        if len(m.calls) == 3:
            break
        time.sleep(0.01)
    assert [c[1] for c in m.calls] == ["a", "b", "c"]


def test_kill_switch_and_risk_policy_stop_orders_before_the_mirror(tmp_path):
    b, m, _ = mirrored()
    manager = OrderManager(b, Store(str(tmp_path / "t.db")), RiskPolicy(), clock=lambda: NOW)
    manager.set_kill_switch(True, "test")
    order = manager.submit(make_intent())
    assert order.state.value == "RISK_REJECTED" and m.calls == []
    assert manager.submit(make_intent("key-big", qty=50)).state.value == "RISK_REJECTED" and m.calls == []
    manager.set_kill_switch(False)
    assert manager.submit(make_intent("key-ok")).state.value == "FILLED"
    assert m.calls == [("submit", "key-ok", Side.BUY_TO_OPEN)]


def test_restart_restore_does_not_resend_old_orders(tmp_path):
    b, m, _ = mirrored()
    store = Store(str(tmp_path / "t.db"))
    manager = OrderManager(b, store, RiskPolicy(), clock=lambda: NOW)
    assert manager.submit(make_intent()).state.value == "FILLED"
    sent = list(m.calls)
    fresh, m2, _ = mirrored()
    fresh.restore(store.list_orders(limit=1000))
    assert sent and fresh.get_positions() == b.get_positions() != [] and m2.calls == []
