from dataclasses import replace

from helpers import make_intent, make_quote
from optplat.broker import SimBroker
from optplat.models import Side
from optplat.orders import OrderManager
from optplat.store import Store
from test_sell_flow import Clock


def _mgr():
    broker = SimBroker()
    broker.set_quote(make_quote())
    return OrderManager(broker, Store(":memory:"), clock=Clock()), broker


def test_empty_report_marked_fields():
    m, _ = _mgr()
    r = m.report()
    assert r["marked_pnl"] == 0 and r["marked_pnl_complete"] is True
    assert r["open_positions_unobservable"] == 0 and r["history_truncated"] is False


def test_open_position_unrealized_included_in_marked_pnl():
    m, _ = _mgr()
    m.submit(make_intent("k1-00000001"))
    r = m.report()
    assert len(r["open"]) == 1
    expected = r["open"][0]["unrealized_pnl"]
    assert r["open_unrealized_pnl"] == expected
    assert r["marked_pnl"] == round(r["realized_pnl"] + expected, 2)
    assert r["marked_pnl_complete"] is True


def test_unobservable_open_mark_flags_incomplete():
    m, broker = _mgr()
    m.submit(make_intent("k1-00000001"))
    broker.set_quote(replace(make_quote(), bid=0.0))
    r = m.report()
    assert r["open_positions_unobservable"] == 1
    assert r["marked_pnl_complete"] is False
    assert r["open_unrealized_pnl"] == 0


def test_history_truncated_flag():
    m, _ = _mgr()
    m.submit(make_intent("k1-00000001"))
    m.submit(make_intent("k2-00000002"))
    m.REPORT_HISTORY_LIMIT = 2
    assert m.report()["history_truncated"] is True
    m.REPORT_HISTORY_LIMIT = 1000
    assert m.report()["history_truncated"] is False
