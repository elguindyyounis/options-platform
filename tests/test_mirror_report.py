"""Simulated vs IBKR paper fill report, and the mirror's read-back of working orders (synthetic fixtures only)."""
from helpers import NOW, make_intent, make_quote
from optplat.broker.mirror import MirroredSimBroker
from optplat.mirror_report import main, report
from optplat.models import BrokerOrderStatus, Order, OrderState, Side
from optplat.store import Store


def _order(store, key, *, side=Side.BUY_TO_OPEN, qty=4, filled=4, px=2.00, state=OrderState.FILLED):
    o = Order.new(make_intent(key, qty=qty, limit=2.10, side=side), NOW)
    o.state, o.filled_qty, o.avg_fill_price = state, filled, px
    store.insert_order(o)
    return o


def _ib(store, kind, key, status, filled, px):
    store.audit(kind, None, {"idempotency_key": key, "status": status, "filled_qty": filled, "avg_fill_price": px})


def test_pairs_each_order_with_its_last_ibkr_outcome_and_signs_the_gap_from_the_traders_side():
    s = Store()
    _order(s, "buy")                                   # sim bought at 2.00
    _order(s, "sell", side=Side.SELL_TO_CLOSE)         # sim sold at 2.00
    _order(s, "rest", filled=0, px=None, state=OrderState.SUBMITTED)
    _ib(s, "ibkr_mirror_submitted", "buy", "SUBMITTED", 0, None)
    _ib(s, "ibkr_mirror_status", "buy", "FILLED", 4, 1.95)       # IBKR bought cheaper: better by 0.05
    _ib(s, "ibkr_mirror_submitted", "sell", "FILLED", 4, 1.90)   # IBKR sold lower: worse by 0.10
    _ib(s, "ibkr_mirror_submitted", "rest", "SUBMITTED", 0, None)
    out = report(s)
    rows = {r["idempotency_key"]: r for r in out["orders"]}
    assert rows["buy"]["ibkr_better_by_per_share"] == 0.05 and rows["buy"]["ibkr_better_by_usd"] == 20.0
    assert rows["sell"]["ibkr_better_by_per_share"] == -0.10 and rows["sell"]["ibkr_better_by_usd"] == -40.0
    assert rows["rest"]["ibkr_better_by_per_share"] is None
    sm = out["summary"]
    assert (sm["mirrored_orders"], sm["both_filled"], sm["ibkr_last_known_working"]) == (3, 2, 1)
    assert sm["ibkr_better_by_usd_total"] == -20.0
    assert any("too few" in n for n in out["notes"]) and any("simulator" in n for n in out["notes"])


def test_counts_misses_rejections_errors_and_drops():
    s = Store()
    _order(s, "missed")
    _order(s, "refused")
    _ib(s, "ibkr_mirror_cancelled", "missed", "CANCELLED", 0, None)
    s.audit("ibkr_mirror_rejected", None, {"idempotency_key": "refused", "reason": "over the size ceiling"})
    s.audit("ibkr_mirror_error", None, {"error": "ConnectionError"})
    s.audit("ibkr_mirror_dropped", None, {"reason": "backlog full"})
    _ib(s, "ibkr_mirror_submitted", "not-ours", "FILLED", 1, 1.0)
    sm = report(s)["summary"]
    assert sm["sim_filled_ibkr_not"] == 2 and sm["ibkr_filled"] == 0
    assert sm["rejected_reasons"] == {"over the size ceiling": 1} and sm["error_types"] == {"ConnectionError": 1}
    assert sm["dropped"] == 1 and sm["outcomes_without_a_local_order"] == 1


def test_cli_opens_the_database_read_only(tmp_path, capsys):
    db = tmp_path / "p.db"
    s = Store(str(db))
    _order(s, "buy")
    _ib(s, "ibkr_mirror_submitted", "buy", "FILLED", 4, 2.00)
    before = db.read_bytes()
    main(["--db", str(db), "--summary"])
    assert '"both_filled": 1' in capsys.readouterr().out
    assert db.read_bytes() == before


class SlowFillMirror:
    """Accepts and rests the order; it fills later. Records every call so the read-back is shown to be read-only."""

    def __init__(self):
        self.calls, self.states, self.fail = [], {}, False

    def submit_limit_order(self, intent):
        self.calls.append("submit")
        self.states[intent.idempotency_key] = BrokerOrderStatus("ibkr:" + intent.idempotency_key,
                                                                intent.idempotency_key, "SUBMITTED", 0, None)
        return self.states[intent.idempotency_key]

    def get_order_status(self, broker_order_id):
        self.calls.append("status")
        if self.fail:
            raise ConnectionError("TWS closed")
        return self.states[broker_order_id[5:]]

    def cancel_order(self, broker_order_id):
        raise AssertionError("the read-back must never cancel")


def test_idle_read_back_audits_a_later_fill_once_then_stops_following_it():
    m = SlowFillMirror()
    b = MirroredSimBroker(m, background=False)
    events = []
    b.attach_audit(lambda kind, oid, payload: events.append((kind, payload)))
    b.set_quote(make_quote())
    b.submit_limit_order(make_intent(limit=2.50))
    b.poll_working()                                   # nothing changed: nothing audited
    assert [k for k, _ in events] == ["ibkr_mirror_submitted"]
    m.fail = True
    b.poll_working()                                   # unreachable: skipped quietly, still followed
    m.fail = False
    m.states["key-00000001"] = BrokerOrderStatus("ibkr:key-00000001", "key-00000001", "FILLED", 4, 2.01)
    b.poll_working()
    b.poll_working()                                   # terminal: no longer asked about
    assert [k for k, _ in events] == ["ibkr_mirror_submitted", "ibkr_mirror_status"]
    assert events[1][1] == {"idempotency_key": "key-00000001", "status": "FILLED", "filled_qty": 4,
                            "avg_fill_price": 2.01}
    assert m.calls == ["submit", "status", "status", "status"]


def test_an_order_ibkr_cannot_find_stops_being_followed_after_max_misses():
    from optplat.broker import mirror as mod
    m = SlowFillMirror()
    b = MirroredSimBroker(m, background=False)
    b.set_quote(make_quote())
    b.submit_limit_order(make_intent(limit=2.50))
    m.fail = True
    for _ in range(mod.MAX_MISSES):
        b.poll_working()
    asked = m.calls.count("status")
    b.poll_working()
    assert asked == mod.MAX_MISSES and m.calls.count("status") == asked
