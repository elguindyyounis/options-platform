import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import test_optionlanes as tol
from fastapi.testclient import TestClient

from optplat import optionlanes as ol
from optplat import reviewer as rv
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, TradingEngine
from optplat.marketdata import DemoDataProvider
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy

NOW = datetime(2026, 11, 20, 15, 0, tzinfo=timezone.utc)


def a(kind="swing", entry=2.0, bid=2.0, peak=None, days=1.0, dte=30):
    opened = (NOW - timedelta(days=days)).isoformat()
    return rv.assess(kind=kind, entry=entry, bid=bid, peak_bid=peak if peak is not None else bid, opened_at=opened,
                     expiry=(NOW.date() + timedelta(days=dte)).isoformat(), now=NOW)


# ---------------------------------------------------------------- the rules
def test_a_position_with_nothing_wrong_is_held_and_says_so():
    r = a(bid=2.1)
    assert r["verdict"] == "HOLD" and r["flags"] == [] and r["pnl_pct"] == 5.0


def test_giving_back_half_of_a_big_gain_is_flagged_for_every_kind_but_a_small_gain_is_not():
    for kind in ("short", "swing", "flow"):
        assert a(kind=kind, entry=2.0, bid=2.6, peak=3.2)["flags"] == ["gave_back"]          # peak +60%, now +30%: half gone
    assert a(entry=2.0, bid=2.9, peak=3.2)["flags"] == []                                      # still +45% of a +60% peak
    assert a(entry=2.0, bid=2.1, peak=2.4)["flags"] == []                                      # a +20% peak is not big enough to matter


def test_a_trade_that_never_worked_is_flagged_only_for_swing_and_flow_and_only_after_three_days():
    assert a(kind="swing", bid=1.7, days=3.5)["flags"] == ["never_worked"]
    assert a(kind="flow", bid=1.7, days=3.5)["flags"] == ["never_worked"]
    assert a(kind="short", bid=1.7, days=3.5)["flags"] == []
    assert a(kind="swing", bid=1.7, days=2.0)["flags"] == []                                   # too soon
    assert a(kind="swing", bid=1.7, peak=2.2, days=3.5)["flags"] == []                         # it did work for a while (+10%)
    assert a(kind="swing", bid=1.85, days=3.5)["flags"] == []                                  # down only 7.5%


def test_a_losing_trade_close_to_expiry_is_flagged_and_a_winning_one_is_not():
    assert "late_and_losing" in a(kind="swing", bid=1.9, dte=6)["flags"]
    assert a(kind="swing", bid=2.2, dte=6)["flags"] == []
    assert a(kind="swing", bid=1.9, dte=8)["flags"] == []
    assert a(kind="short", bid=1.9, dte=2)["flags"] == []


def test_bad_inputs_give_unknown_not_a_guess():
    for bad in (dict(entry=0.0), dict(entry=float("nan")), dict(bid=float("nan")), dict(bid=-1.0)):
        assert a(**bad)["verdict"] == "UNKNOWN"


# ---------------------------------------------------------------- the scorecard
def call(rule, entry, bid, exit_price):
    return {"rule": rule, "entry_price": entry, "bid": bid, "exit_price": exit_price}


def test_a_call_is_scored_as_what_leaving_then_would_have_saved_as_a_share_of_the_premium():
    c = rv.scorecard([call("gave_back", 2.0, 2.6, 2.0), call("gave_back", 2.0, 2.6, 3.0)])
    g = next(r for r in c["rules"] if r["rule"] == "gave_back")
    # exiting at 2.6 against a real exit of 2.0 saves 30 points of the 2.0 premium; against a real exit of 3.0 it loses 20; the average is +5
    assert g["scored"] == 2 and g["avg_benefit_pts"] == 5.0 and g["earlier_was_better_pct"] == 50.0 and g["verdict"] == "too_few"


def test_calls_on_open_trades_count_as_calls_but_are_not_scored_yet():
    c = rv.scorecard([call("never_worked", 2.0, 1.7, None)])
    r = next(x for x in c["rules"] if x["rule"] == "never_worked")
    assert r["calls"] == 1 and r["scored"] == 0 and "avg_benefit_pts" not in r


def test_a_verdict_needs_the_minimum_and_then_follows_the_average():
    helped = rv.scorecard([call("gave_back", 2.0, 2.6, 2.0)] * 20)
    assert next(x for x in helped["rules"] if x["rule"] == "gave_back")["verdict"] == "earlier_helped"
    hurt = rv.scorecard([call("gave_back", 2.0, 2.6, 3.2)] * 20)
    assert next(x for x in hurt["rules"] if x["rule"] == "gave_back")["verdict"] == "earlier_hurt"
    flat = rv.scorecard([call("gave_back", 2.0, 2.6, 2.61)] * 20)
    assert next(x for x in flat["rules"] if x["rule"] == "gave_back")["verdict"] == "no_clear_difference"
    assert next(x for x in rv.scorecard([call("gave_back", 2.0, 2.6, 2.0)] * 19)["rules"] if x["rule"] == "gave_back")["verdict"] == "too_few"


# ---------------------------------------------------------------- inside a lane
def open_one():
    names = ("SPY",)
    data, now = tol.downtrend_daily(names)
    lane, prov, store, box = tol.make(replace(ol.CONTROL, symbols=names, budget_usd=20000.0), daily=data, now=now)
    lane.step(force=True)
    (t,) = tol.opened(lane, prov, store)
    return lane, prov, store, t, lane.clock()


def mark(store, t, bid, at):
    store.set_state(f"lane_mark:{t['id']}", json.dumps({"bid": bid, "ask": bid + 0.05, "at": at.isoformat()}))


def test_the_lane_reviews_each_open_position_records_its_calls_and_never_closes_it():
    lane, prov, store, t, now = open_one()
    entry = t["entry_price"]
    mark(store, t, entry * 1.6, now)                       # up 60%: the peak
    lane._advise(now)
    mark(store, t, entry * 1.3, now + timedelta(hours=1))  # back to +30%: half of the peak gain is gone
    lane._advise(now + timedelta(hours=1))
    state = json.loads(store.get_state(f"optlane_review:{t['id']}"))
    assert state["verdict"] == "CONSIDER_EXIT" and state["flags"] == ["gave_back"] and state["peak_pnl_pct"] == 60.0
    assert [c["rule"] for c in store.review_calls(prov.fictional)] == ["gave_back"]
    assert [x["id"] for x in lane._held()] == [t["id"]]    # still open: the reviewer advises, nothing more
    lane._advise(now + timedelta(hours=2))                 # no fresh mark: no new review, and no duplicate call
    assert len(store.review_calls(prov.fictional)) == 1


def test_a_stale_mark_is_not_reviewed():
    lane, prov, store, t, now = open_one()
    mark(store, t, t["entry_price"] * 0.5, now - timedelta(hours=3))
    lane._advise(now)
    assert store.get_state(f"optlane_review:{t['id']}") == "" and store.review_calls(prov.fictional) == []


def test_a_call_is_scored_after_the_trade_closes_by_its_normal_rule():
    lane, prov, store, t, now = open_one()
    entry = t["entry_price"]
    mark(store, t, entry * 1.6, now)
    lane._advise(now)
    mark(store, t, entry * 1.3, now + timedelta(hours=1))
    lane._advise(now + timedelta(hours=1))
    store.lane_close(t["id"], now + timedelta(days=2), entry * 0.7, "stop", {})
    c = rv.scorecard(store.review_calls(prov.fictional))
    g = next(r for r in c["rules"] if r["rule"] == "gave_back")
    assert g["scored"] == 1 and g["avg_benefit_pts"] == 60.0     # called at +30% (1.3x), closed at 0.7x: leaving early saved 60 points of the premium
    assert g["earlier_was_better_pct"] == 100.0


# ---------------------------------------------------------------- the endpoint
def test_the_review_endpoint_needs_the_token_and_lists_open_trades_with_their_latest_review():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    with TestClient(create_app(manager, "t" * 24, engine, None)) as c:
        assert c.get("/api/reviews").status_code == 401
        empty = c.get("/api/reviews", headers={"X-API-Token": "t" * 24}).json()
        assert empty["open"] == [] and empty["advisory"] is True and {r["rule"] for r in empty["scorecard"]["rules"]} == set(rv.RULES)
        lane = engine.option_lanes.lanes[0]
        tid = engine.store.lane_open(lane.p.lane, "SPY", NOW, 2.0, 3, engine.provider.fictional,
                                     {"contract": "SPY   261218C00700000", "right": "C", "strike": 700.0, "expiry": "2026-12-18"})
        engine.store.set_state(f"optlane_review:{tid}", json.dumps(rv.assess(kind="short", entry=2.0, bid=2.6, peak_bid=3.2,
                                                                          opened_at=NOW.isoformat(), expiry="2026-12-18", now=NOW)))
        body = c.get("/api/reviews", headers={"X-API-Token": "t" * 24}).json()
        js = c.get("/static/app.js").text
    (row,) = body["open"]
    assert row["review"]["verdict"] == "CONSIDER_EXIT" and "gave_back" in row["rule_text"] and row["contract"].startswith("SPY call 700")
    assert "renderReviews" in js and "/api/reviews" in js
