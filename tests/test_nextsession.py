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


def test_the_plan_has_its_own_page_and_one_line_on_the_desk_without_assigning_html(client):
    c, _ = client
    html, js = c.get("/").text, c.get("/static/app.js").text
    assert 'id="view-nextopen"' in html and 'id="ns-desk-line"' in html and 'id="next-session"' not in html
    assert '"/api/next-session/review"' in js and "Nothing is ordered from this page." in js and "innerHTML" not in js
    assert "Nothing here is 100%" in js


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


# ------------------------------------------------------------ certainty tiers and planned vs taken
def plan_with(**lane):
    base = {"lane": "swing-options-aggr", "label": "Swing options, aggressive", "max_entries": 3,
            "buys": [], "queued": [], "sells": [], "blocked": [], "holds": []}
    return ns.add_tiers({"lanes": [{**base, **lane}]})


def test_tiers_follow_what_the_open_can_still_change():
    p = plan_with(sells=[{"symbol": "A", "reason": "time"}, {"symbol": "B", "reason": "stop"}],
                  buys=[{"symbol": "C", "rank": 1}, {"symbol": "D", "rank": 4}],
                  queued=[{"symbol": "E", "rank": 2}], blocked=[{"symbol": "F", "reason": "x"}])
    lane = p["lanes"][0]
    assert [x["tier"] for x in lane["sells"]] == ["WILL_SELL", "LIKELY_SELL"]
    assert [(x["tier"], x["below_cut"]) for x in lane["buys"]] == [("LIKELY_BUY", False), ("POSSIBLE_BUY", True)]
    assert lane["queued"][0]["tier"] == "POSSIBLE_BUY" and not lane["queued"][0]["below_cut"]
    assert lane["blocked"][0]["tier"] == "WONT"
    assert p["tiers"] == {"WILL_SELL": 1, "LIKELY_SELL": 1, "LIKELY_BUY": 1, "POSSIBLE_BUY": 2, "WONT": 1}


def test_share_lane_exits_are_fixed_by_the_bar():
    p = ns.add_tiers({"lanes": [{"lane": "swing-pullback", "sells": [{"symbol": "A", "reason": "stop"}], "buys": [], "queued": [], "blocked": []}]})
    assert p["lanes"][0]["sells"][0]["tier"] == "WILL_SELL"


def test_preview_ranks_follow_the_lanes_try_order():
    lane, prov, store, box, now, session = lane_and_session()
    plan = ns._swing_option_lane(lane, now, session)
    assert plan["buys"][0]["rank"] == 1 and plan["max_entries"] == ol.MAX_ENTRIES_PER_STEP


def test_review_matches_the_saved_plan_against_what_the_lane_did():
    data, now = uptrend()
    lane, prov, store, box = make(replace(ol.SWING_AGGR, symbols=("AAPL",), budget_usd=20000.0), daily=data, now=now)
    session = ns.next_session(now)
    plan = ns.add_tiers({"next_session": session, "built_at": now.isoformat(), "lanes": [ns._swing_option_lane(lane, now, session)]})
    store.set_state(f"{ns.STATE_KEY}:{session['date']}", json.dumps(plan))
    store.set_state(f"{ns.STATE_KEY}:index", json.dumps([session["date"]]))
    opens = datetime.fromisoformat(session["opens_at"])
    assert ns.review_history(store, True, opens - timedelta(minutes=5))["sessions"] == 0     # not started yet
    box[0] = opens + timedelta(minutes=30)
    lane.feed._cache.clear()
    lane.step(force=True)
    hist = ns.review_history(store, True, opens + timedelta(hours=3))
    assert hist["sessions"] == 1 and hist["by_tier"]["LIKELY_BUY"] == {"planned": 1, "taken": 1} and hist["unplanned"] == 0
    line = hist["latest"]["lines"][0]
    assert line["taken"] and line["taken_contract"] == line["planned_contract"]


def test_review_without_a_plan_says_so():
    assert ns.review(Store(":memory:"), True, "2026-11-30")["status"] == "NO_PLAN"


def test_refresh_keeps_one_plan_per_session_for_the_review(client):
    c, engine = client
    engine.set_config({"option_lanes_enabled": True})
    engine.clock = lambda: ny(2026, 11, 27, 18)
    ns.refresh(engine)
    assert json.loads(engine.store.get_state(f"{ns.STATE_KEY}:index")) == ["2026-11-30"]
    assert json.loads(engine.store.get_state(f"{ns.STATE_KEY}:2026-11-30"))["tiers"] is not None
    assert c.get("/api/next-session/review", headers=H).json()["sessions"] == 0
    assert c.get("/api/next-session/review").status_code == 401


def test_unverified_ibkr_chains_are_named_as_the_reason():
    lane, prov, store, box, now, session = lane_and_session()
    base = prov.snapshot_window

    def ibkr(symbol, *a, **k):
        return replace(base(symbol, *a, **k), source="ibkr-shared-research-only", timestamp_verified=False)
    prov.snapshot_window = ibkr
    plan = ns._swing_option_lane(lane, now, session)
    assert plan["buys"] == [] and "not verified" in plan["blocked"][0]["reason"]
