"""Paper account size and fresh starts (owner decision 2026-11-27: size the paper account like the planned $1,000)."""
import json
from datetime import timedelta

import pytest

from helpers import NOW, make_intent
from optplat import account as acct
from optplat.broker.sim import SimBroker
from optplat.models import Order, OrderState
from optplat.risk import RiskPolicy
from optplat.store import Store


def test_defaults_change_nothing():
    assert acct.start_cash({}) == 100_000.0
    assert acct.risk_policy({}, require_verified_quote_time=True) == RiskPolicy()
    assert acct.resolve_epoch("", 100_000.0, NOW) == (None, False)


def test_owner_limits_apply_and_bad_values_refuse_to_start():
    p = acct.risk_policy({"OPTPLAT_MAX_POSITION_PCT": "35", "OPTPLAT_MAX_TOTAL_PREMIUM_PCT": "70"}, require_verified_quote_time=True)
    assert (p.max_position_pct, p.max_total_premium_pct, p.version) == (35.0, 70.0, "risk-v1-owner")
    assert p.max_spread_pct_of_ask == RiskPolicy().max_spread_pct_of_ask and p.require_verified_quote_time is True
    for env in ({"OPTPLAT_MAX_POSITION_PCT": "60"}, {"OPTPLAT_MAX_POSITION_PCT": "abc"},
                {"OPTPLAT_MAX_POSITION_PCT": "20", "OPTPLAT_MAX_TOTAL_PREMIUM_PCT": "10"}):
        with pytest.raises(ValueError):
            acct.risk_policy(env, require_verified_quote_time=True)
    with pytest.raises(ValueError):
        acct.start_cash({"OPTPLAT_PAPER_START_CASH": "50"})


def test_epoch_starts_once_per_size_change():
    e1, new1 = acct.resolve_epoch("", 1000.0, NOW)
    assert new1 and e1 == {"start_cash": 1000.0, "started_at": NOW.isoformat()}
    assert acct.resolve_epoch(json.dumps(e1), 1000.0, NOW + timedelta(days=1)) == (e1, False)  # a restart keeps it
    e2, new2 = acct.resolve_epoch(json.dumps(e1), 2500.0, NOW + timedelta(days=2))
    assert new2 and e2["start_cash"] == 2500.0
    e3, new3 = acct.resolve_epoch(json.dumps(e1), 100_000.0, NOW + timedelta(days=3))  # going back is a new start too
    assert new3 and e3["start_cash"] == 100_000.0
    assert acct.resolve_epoch("not json", 1000.0, NOW)[1] is True


def _filled(store, key, created, *, price=2.0, qty=1):
    o = Order.new(make_intent(key, qty=qty, limit=price), created)
    o.state, o.filled_qty, o.avg_fill_price, o.broker_order_id = OrderState.FILLED, qty, price, "b-" + key
    store.insert_order(o)
    return o


def test_a_new_size_starts_a_clean_account_and_keeps_the_old_history():
    store = Store()
    _filled(store, "old-1", NOW - timedelta(days=3))                      # an open position in the $100k account
    store.record_equity(NOW - timedelta(days=3), 99_900.0, 99_800.0, 200.0, False)
    ep = acct.start_account(store, 1000.0, NOW)
    assert ep["started_now"] and ep["open_positions_left"] == 1 and store.account_since == NOW.isoformat()
    assert store.list_orders(limit=100) == [] and len(store.list_orders(limit=100, all_history=True)) == 1
    assert any(e["kind"] == "account_epoch_started" for e in store.audit_events())
    store.record_equity(NOW + timedelta(minutes=1), 1000.0, 1000.0, 0.0, False)
    assert [p["equity"] for p in store.list_equity()] == [1000.0]  # the old curve is history, not this account's
    assert len(store.list_equity(all_history=True)) == 2
    _filled(store, "new-1", NOW + timedelta(minutes=5), price=3.0)
    broker = SimBroker(starting_cash=1000.0)
    out = broker.restore(store.list_orders(limit=1_000_000))
    assert out["orders_replayed"] == 1 and out["open_positions"] == 1 and out["cash"] == round(1000.0 - 3.0 * 100, 2)
    # restarting with the same size keeps the same start, and nothing is logged twice
    store.account_since = None
    again = acct.start_account(store, 1000.0, NOW + timedelta(days=1))
    assert not again["started_now"] and store.account_since == NOW.isoformat()
    assert sum(e["kind"] == "account_epoch_started" for e in store.audit_events()) == 1


def test_never_resized_means_everything_counts():
    store = Store()
    _filled(store, "a", NOW)
    assert acct.start_account(store, 100_000.0, NOW) is None and store.account_since is None
    assert len(store.list_orders(limit=10)) == 1
