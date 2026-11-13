from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from optplat import tracker as tr
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, TradingEngine
from optplat.marketdata import ChainRow, DemoDataProvider, MarketSnapshot
from optplat.models import OptionContract, Right
from optplat.orders import OrderManager
from optplat.scanner import compare_with_prior, unusual_criteria
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy

D0 = date(2026, 11, 9)   # a Monday
EXP = date(2026, 12, 18)
OCC = OptionContract("AAA", EXP, Right.CALL, 100.0).occ_symbol.strip()
PUT_OCC = OptionContract("AAA", EXP, Right.PUT, 100.0).occ_symbol.strip()
NOWTS = datetime(2026, 11, 12, 16, tzinfo=timezone.utc)


def sighting(**kw):
    base = {"symbol": "AAA", "contract": OCC, "right": "C", "strike": 100.0, "expiry": EXP.isoformat(), "dte": 39, "volume": 900,
            "open_interest": 100, "volume_oi_ratio": 9.0, "low_oi": False, "likely_side": "BUY", "liquidity_tier": "B", "sector": "Tech",
            "ask": 2.0, "bid": 1.9, "underlying_price": 100.0, "score": 70.0}
    return {**base, **kw}


def snap(day_offset_spot=103.0, bid=2.6, ask=2.8, oi=500, right=Right.CALL):
    c = OptionContract("AAA", EXP, right, 100.0)
    row = ChainRow(c, bid, ask, 50, oi, 0.3)
    return MarketSnapshot("AAA", day_offset_spot, (day_offset_spot,) * 5, (row,), NOWTS, "t", True, True)


def seed(store, **kw):
    s = sighting(**kw)
    store.record_unusual(D0.isoformat(), True, [s])
    return s


def test_trading_days_skip_weekends_and_listed_holidays():
    assert tr.trading_days_between(date(2026, 11, 12), date(2026, 11, 16)) == 2
    assert tr.trading_days_between(date(2026, 11, 16), date(2026, 11, 16)) == 0
    assert tr.trading_days_between(date(2026, 11, 20), date(2026, 11, 30)) == 5  # Thanksgiving is closed


@pytest.mark.parametrize("age,done,due", [(0, set(), []), (1, set(), [1]), (2, {1}, []), (3, {1}, [3]), (5, {1}, [3]), (6, {1}, []), (7, {1, 3}, [7]), (9, {1, 3}, [7]), (10, {1, 3}, [])])
def test_a_mark_is_taken_once_never_early_and_not_too_late(age, done, due):
    assert tr.horizons_due(age, done) == due


def test_a_later_scan_records_the_ask_in_bid_out_return_and_the_helpful_move():
    store = Store(":memory:")
    s = seed(store)
    n = tr.observe(store, snap(oi=600), date(2026, 11, 10), True, compare_with_prior)   # 1 trading day later
    assert n == 1
    m = store.tracker_marks(True)[0]
    assert m["horizon"] == 1 and m["ret_pct"] == round((2.6 / 2.0 - 1) * 100, 2) == 30.0
    assert m["move_pct"] == 3.0 and m["helpful_move_pct"] == 3.0 and m["features"]["ratio"] == "5 to 10 times"
    assert m["oi_verdict"] == "OI_ROSE"   # open interest went from 100 to 600 against 900 traded
    assert tr.observe(store, snap(), date(2026, 11, 10), True, compare_with_prior) == 0   # the same mark is never taken twice


def test_a_put_is_helped_by_the_underlying_falling_and_a_missing_quote_leaves_a_gap_not_a_guess():
    store = Store(":memory:")
    seed(store, contract=PUT_OCC, right="P")
    assert tr.observe(store, snap(day_offset_spot=95.0, right=Right.PUT), date(2026, 11, 10), True, compare_with_prior) == 1
    assert store.tracker_marks(True)[0]["helpful_move_pct"] == 5.0
    store2 = Store(":memory:")
    seed(store2)
    assert tr.observe(store2, snap(right=Right.PUT), date(2026, 11, 10), True, compare_with_prior) == 0   # that contract is not in the chain
    assert tr.observe(store2, snap(bid=0.0), date(2026, 11, 10), True, compare_with_prior) == 1 and store2.tracker_marks(True)[0]["ret_pct"] == -100.0


def test_fictional_and_real_sightings_are_kept_apart_and_today_is_never_marked_against_itself():
    store = Store(":memory:")
    seed(store)
    assert tr.observe(store, snap(), date(2026, 11, 10), False, compare_with_prior) == 0
    assert tr.observe(store, snap(), D0, True, compare_with_prior) == 0


def marks(n, ret, **feat):
    return [{"horizon": 3, "ret_pct": ret, "helpful_move_pct": 1.0, "oi_verdict": "OI_FLAT_OR_MIXED", "features": {"ratio": "25 times or more", **feat}} for _ in range(n)]


def test_small_groups_are_shown_but_never_called_findings():
    few = marks(5, 40.0) + marks(40, -10.0, ratio="3 to 5 times")
    out = tr.summarize(few)
    big = next(g for g in out["groups"] if g["bucket"] == "3 to 5 times" and g["horizon"] == 3)
    small = next(g for g in out["groups"] if g["bucket"] == "25 times or more" and g["horizon"] == 3)
    assert big["enough"] and not small["enough"]
    assert not any("25 times or more" in f for f in out["findings"])


def test_a_big_group_that_differs_from_the_average_becomes_a_plain_sentence():
    data = marks(30, 25.0) + marks(30, -25.0, ratio="3 to 5 times")
    out = tr.summarize(data)
    assert any("volume against open interest" in f.lower() and "better" in f for f in out["findings"])
    assert out["horizons"]["3"]["n"] == 60 and out["horizons"]["1"]["n"] == 0 and out["horizons"]["1"]["avg_ret_pct"] is None


def test_the_criteria_are_listed_with_the_real_thresholds():
    text = " ".join(c["rule"] for c in unusual_criteria())
    assert "150" in text and "3 times" in text and "500" in text


def test_the_tracker_endpoint_returns_criteria_marks_and_the_watch_list():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    engine.store.record_unusual(engine.clock().astimezone().date().isoformat(), True, [sighting()])
    with TestClient(create_app(manager, "t" * 24, engine, None)) as c:
        assert c.get("/api/tracker").status_code == 401
        body = c.get("/api/tracker", headers={"X-API-Token": "t" * 24}).json()
    assert body["criteria"] and body["limitations"] and body["total_marks"] == 0 and body["fictional"] is True
    assert set(body["horizons"]) == {"1", "3", "7"} and body["findings"] == []


def test_the_rotation_endpoint_reads_stored_scans():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    with TestClient(create_app(manager, "t" * 24, engine, None)) as c:
        assert c.get("/api/rotation").status_code == 401
        body = c.get("/api/rotation", headers={"X-API-Token": "t" * 24}).json()
    assert body["ready"] is False and body["sectors"] == [] and body["caveat"]
