from dataclasses import replace

import pytest

from helpers import make_intent, make_quote
from optplat.broker import SimBroker
from optplat.models import OrderIntent, Side
from optplat.orders import OrderManager
from optplat.store import Store
from test_sell_flow import Clock


def _mgr():
    broker = SimBroker()
    broker.set_quote(make_quote())
    return OrderManager(broker, Store(":memory:"), clock=Clock())


def _round_trip(m, key, buy_src, sell_src):
    m.submit(replace(make_intent(key + "-b"), data_source=buy_src))
    return m.submit(replace(make_intent(key + "-s", limit=1.88, side=Side.SELL_TO_CLOSE), data_source=sell_src))


def test_intent_data_source_round_trips_and_defaults_empty():
    i = replace(make_intent(), data_source="yahoo-unofficial")
    assert OrderIntent.from_dict(i.to_dict()).data_source == "yahoo-unofficial"
    d = make_intent().to_dict()
    d.pop("data_source")
    assert OrderIntent.from_dict(d).data_source == ""


def test_closed_trades_carry_their_data_source():
    m = _mgr()
    _round_trip(m, "k1-00000001", "demo-synthetic", "demo-synthetic")
    r = m.report()
    c = r["closed"][0]
    assert c["entry_data_source"] == c["exit_data_source"] == "demo-synthetic"
    assert r["by_data_source"] == {"demo-synthetic": {"closed_trades": 1, "realized_pnl": r["realized_pnl"]}}
    assert r["data_sources_mixed"] is False


def test_manual_orders_are_unknown_not_assumed_real():
    m = _mgr()
    _round_trip(m, "k2-00000001", "", "")
    r = m.report()
    assert r["closed"][0]["entry_data_source"] == "UNKNOWN"
    assert "UNKNOWN" in r["by_data_source"]


def test_entry_and_exit_from_different_sources_are_flagged_mixed():
    m = _mgr()
    _round_trip(m, "k3-00000001", "demo-synthetic", "yahoo-unofficial")
    r = m.report()
    assert list(r["by_data_source"]) == ["MIXED"]
    assert r["data_sources_mixed"] is True
