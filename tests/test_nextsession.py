"""The next-session preview: same rules as the lanes, no side effects, built once per closed period."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from optplat import nextsession as ns
from optplat import optionlanes as ol
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, TradingEngine
from optplat.market_clock import NY
from optplat.marketdata import DemoDataProvider
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy
from test_optionlanes import H, TOKEN, make, opened, uptrend


def ny(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=NY)


# ------------------------------------------------------------ calendar
def test_next_session_skips_weekends_and_holidays_and_flags_early_closes():
    s = ns.next_session(ny(2026, 11, 27, 14))                 # Friday after the 1 pm early close
    assert s["date"] == "2026-11-30" and s["closed_days_before"] == ["2026-11-28", "2026-11-29"] and not s["early_close"]
    s = ns.next_session(ny(2026, 11, 25, 18))                 # Wednesday evening, Thanksgiving next
    assert s["date"] == "2026-11-27" and s["early_close"] and s["closed_days_before"] == ["2026-11-26"]
    assert ns.next_session(ny(2026, 11, 30, 8))["date"] == "2026-11-30"   # before Monday's open: today
    assert ns.next_session(ny(2026, 11, 30, 10))["date"] == "2026-12-01"  # during the session: tomorrow


def test_no_calendar_means_no_promise():
    assert ns.next_session(ny(2026, 12, 31, 17)) is None     # 2027 table not loaded: fail closed


def test_last_close_uses_the_early_close():
    assert ns.last_close(ny(2026, 11, 28, 9)) == ny(2026, 11, 27, 13).astimezone(timezone.utc)
    assert ns.last_close(ny(2026, 11, 30, 11)) is None        # open now


# ------------------------------------------------------------ the swing option preview
def lane_and_session(params=None):
    data, now = uptrend()
    lane, prov, store, box = make(params or replace(ol.SWING_AGGR, symbols=("AAPL",), budget_usd=20000.0), daily=data, now=now)
    return lane, prov, store, box, now, ns.next_session(now)


def test_preview_names_the_same_trade_the_lane_then_makes_and_changes_nothing():
    lane, prov, store, box, now, session = lane_and_session()
    plan = ns._swing_option_lane(lane, now, session)
    assert len(plan["buys"]) == 1 and not plan["blocked"] and not plan["errors"]
    pick = plan["buys"][0]
    assert pick["symbol"] == "AAPL" and pick["right"] == "C" and pick["quantity"] >= 1
    # no side effects: nothing opened, the bar is still unjudged, no order anywhere
    assert opened(lane, prov, store) == [] and store.get_state(f"optlane_bar:{lane.p.lane}:AAPL", "") == ""
    box[0] = datetime.fromisoformat(session["opens_at"]) + timedelta(minutes=30)
    lane.feed._cache.clear()
    lane.step(force=True)
    t = opened(lane, prov, store)
    assert len(t) == 1 and t[0]["open_payload"]["right"] == pick["right"]
    assert (t[0]["open_payload"]["expiry"], t[0]["open_payload"]["strike"]) == (pick["expiry"], pick["strike"])


def test_a_bar_already_judged_is_not_previewed_again():
    lane, prov, store, box, now, session = lane_and_session()
    lane.step(force=True)
    plan = ns._swing_option_lane(lane, now, session)
    assert plan["buys"] == [] and len(plan["holds"]) == 1


def test_blocked_signals_say_why():
    lane, prov, store, box, now, session = lane_and_session(replace(ol.SWING_BASE, symbols=("AAPL",), budget_usd=20000.0))
    plan = ns._swing_option_lane(lane, now, session)       # no calendar: the base lane needs a clear earnings date
    assert plan["buys"] == [] and "earnings" in plan["blocked"][0]["reason"]
    lane, prov, store, box, now, session = lane_and_session(replace(ol.SWING_AGGR, symbols=("AAPL",), budget_usd=10.0))
    assert "budget" in ns._swing_option_lane(lane, now, session)["blocked"][0]["reason"]


def test_held_trades_show_the_exit_that_is_due():
    lane, prov, store, box, now, session = lane_and_session()
    lane.step(force=True)
    t = opened(lane, prov, store)[0]
    store.set_state(f"lane_mark:{t['id']}", json.dumps({"bid": t["entry_price"] * 0.3, "ask": t["entry_price"] * 0.35, "at": now.isoformat()}))
    plan = ns._swing_option_lane(lane, now, session)
    assert plan["sells"][0]["reason"] == "stop" and plan["sells"][0]["action"] == "WOULD_SELL"
    store.set_state(f"lane_mark:{t['id']}", json.dumps({"bid": t["entry_price"], "ask": t["entry_price"] * 1.05, "at": now.isoformat()}))
    plan = ns._swing_option_lane(lane, now, session)
    assert plan["sells"] == [] and plan["holds"][0]["stop_bid"] < t["entry_price"] < plan["holds"][0]["target_bid"]


def test_missing_daily_bars_are_an_error_not_an_empty_plan():
    lane, prov, store, box, now, session = lane_and_session()
    prov.daily = {}
    lane.feed._cache.clear()

    def boom(*a, **k):
        raise RuntimeError("provider down")
    prov.daily_bars = boom
    plan = ns._swing_option_lane(lane, now, session)
    assert plan["errors"] and plan["buys"] == []


# ------------------------------------------------------------ engine and API
@pytest.fixture
def client():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    with TestClient(create_app(manager, TOKEN, engine, None)) as c:
        yield c, engine


def test_built_once_per_closed_period(client):
    c, engine = client
    engine.set_config({"option_lanes_enabled": True})
    box = [ny(2026, 11, 27, 13, 5)]
    engine.clock = lambda: box[0]
    assert engine.maybe_next_session_plan() is None           # too soon after the 1 pm close
    box[0] = ny(2026, 11, 27, 13, 30)
    plan = engine.maybe_next_session_plan()
    assert plan["status"] == "READY" and plan["next_session"]["date"] == "2026-11-30" and plan["places_orders"] is False
    assert any(x["lane"] == "shortterm-options-aggr" for x in plan["decided_in_session"])
    box[0] = ny(2026, 11, 28, 10)
    assert engine.maybe_next_session_plan() is None           # Saturday: same next session, already built
    box[0] = ny(2026, 11, 30, 11)
    assert engine.maybe_next_session_plan() is None           # never during a session
    box[0] = ny(2026, 11, 30, 16, 30)
    assert engine.maybe_next_session_plan()["next_session"]["date"] == "2026-12-01"


def test_off_when_no_lane_is_on(client):
    c, engine = client
    engine.clock = lambda: ny(2026, 11, 27, 18)
    assert engine.maybe_next_session_plan() is None


def test_api_needs_the_token_and_reports_not_built_first(client):
    c, engine = client
    assert c.get("/api/next-session").status_code == 401
    body = c.get("/api/next-session", headers=H).json()
    assert body["status"] == "NOT_BUILT" and body["places_orders"] is False
    engine.set_config({"option_lanes_enabled": True})
    assert c.post("/api/next-session/refresh", headers=H).json()["places_orders"] is False
    assert c.get("/api/next-session", headers=H).json()["version"] == ns.VERSION


def test_the_desk_shows_the_plan_without_assigning_html(client):
    c, _ = client
    html, js = c.get("/").text, c.get("/static/app.js").text
    assert 'id="next-session"' in html and 'data-question="What will the lanes buy and sell at the next open?"' in html
    assert '"/api/next-session"' in js and "Nothing is ordered from this preview." in js and "innerHTML" not in js


def test_off_hours_chain_problems_queue_the_signal_for_the_open_instead_of_blocking_it():
    lane, prov, store, box, now, session = lane_and_session()

    def no_chain(*a, **k):
        raise TimeoutError("chain closed")
    prov.snapshot_window = no_chain
    plan = ns._swing_option_lane(lane, now, session)
    assert plan["buys"] == [] and plan["blocked"] == []
    assert plan["queued"][0]["symbol"] == "AAPL" and plan["queued"][0]["why_no_contract_yet"] == "TimeoutError"


def test_the_chain_read_cap_is_named_as_such():
    from datetime import date as _d
    lane, prov, store, box, now, session = lane_and_session()
    many = tuple(f"S{i}" for i in range(12))
    data = {s: prov.daily["AAPL"] for s in many}
    lane2, prov2, store2, _ = make(replace(ol.SWING_AGGR, symbols=many, budget_usd=20000.0), daily=data, now=now)

    def no_chain(*a, **k):
        raise TimeoutError("chain closed")
    prov2.snapshot_window = no_chain
    plan = ns._swing_option_lane(lane2, now, session)
    assert len(plan["queued"]) == ol.MAX_CHAIN_READS_PER_STEP
    assert all("option-chain reads" in b["reason"] for b in plan["blocked"]) and len(plan["blocked"]) == 12 - ol.MAX_CHAIN_READS_PER_STEP
