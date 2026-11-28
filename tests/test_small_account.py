from dataclasses import replace
from datetime import timedelta

from optplat import optionlanes as ol
from optplat import small_account as sa
from optplat.alltrades import lane_capital
from optplat.store import Store
from test_optionlanes import OptFeed, short_up

PAY = {"multiplier": 100, "fee_per_contract": 0.65, "fees_open": 0.65, "right": "C", "contract": "Q", "expiry": "2026-12-18", "strike": 1.0}


def build(bars, now):
    box = [now]
    prov = OptFeed(lambda: box[0], bars)
    store = Store(":memory:")
    lane = sa.SmallAccountLane.__new__(sa.SmallAccountLane)
    ol.OptionLane.__init__(lane, prov, store, replace(sa.SMALL, symbols=("SPY",)), ol.Feed(prov, lambda: box[0]), clock=lambda: box[0])
    return lane, prov, store, box


def trades(store):
    return store.lane_trades(sa.LANE, True, 100)


def closed_trade(store, opened, closed, entry, exit_, qty=1):
    tid = store.lane_open(sa.LANE, "QQQ", opened, entry, qty, True, dict(PAY, fees_open=round(0.65 * qty, 2)))
    store.lane_close(tid, closed, exit_, "stop" if exit_ < entry else "target", {"fees_close": round(0.65 * qty, 2)})
    return tid


def test_a_trade_buys_only_a_contract_of_a_dollar_or_less_within_ten_percent_of_equity():
    bars, now = short_up()
    lane, _, store, _ = build(bars, now)
    out = lane.step(force=True)
    t = trades(store)
    assert len(t) == 1, out
    assert t[0]["entry_price"] <= sa.MAX_ASK
    assert t[0]["entry_price"] * t[0]["quantity"] * 100 <= sa.START_EQUITY * sa.RISK_PCT
    assert t[0]["open_payload"]["account_equity"] == sa.START_EQUITY


def test_pick_contract_leaves_out_contracts_over_the_max_ask_and_other_lanes_are_unchanged():
    bars, now = short_up()
    lane, prov, _, _ = build(bars, now)
    snap = prov.snapshot_window("SPY", 0, 4, 3)
    cheap = ol.pick_contract(snap, ol.Right.CALL, now, lane.p, max_ask=1.0)
    free = ol.pick_contract(snap, ol.Right.CALL, now, lane.p)
    assert cheap is not None and cheap.ask <= 1.0
    assert free is not None and free.ask > 1.0   # without the limit the nearer, dearer strike wins
    assert ol.OptionLane.max_ask is None


def test_the_review_refuses_a_contract_over_the_limit_even_if_it_got_through():
    bars, now = short_up()
    lane, prov, _, _ = build(bars, now)
    row = prov.snapshot_window("SPY", 0, 4, 3).rows[0]
    veto, _ = lane._review("SPY", "C", replace(row, ask=1.20), 1, {}, [], now)
    assert veto and "over the $1.00 limit" in veto


def test_money_from_a_trade_closed_today_is_not_settled_until_tomorrow():
    bars, now = short_up()
    lane, _, store, _ = build(bars, now)
    closed_trade(store, now - timedelta(days=1, minutes=30), now - timedelta(days=1), 1.00, 0.50, qty=10)   # yesterday: -$513
    closed_trade(store, now - timedelta(minutes=40), now - timedelta(minutes=20), 0.40, 0.60, qty=5)        # today: +$93.50
    st = lane.state_now(now)
    assert st["unsettled"] == round(0.60 * 5 * 100 - 3.25, 2)
    assert st["settled_cash"] == round(st["cash"] - st["unsettled"], 2)
    assert st["day_start_equity"] == round(1000 - 513, 2) and st["day_pnl"] == round(300 - 3.25 - 200 - 3.25, 2)


def test_no_entry_when_settled_cash_is_used_up():
    bars, now = short_up()
    lane, _, store, _ = build(bars, now)
    # yesterday the account lost almost everything; today one winner closed, but its money has not settled
    closed_trade(store, now - timedelta(days=1, minutes=30), now - timedelta(days=1), 1.00, 0.02, qty=10)
    closed_trade(store, now - timedelta(minutes=40), now - timedelta(minutes=20), 0.10, 0.20, qty=1)
    out = lane.step(force=True)
    assert len(trades(store)) == 2 and any("settled cash" in s for s in out["skips"]), out


def test_the_daily_brake_stops_new_entries_after_a_ten_percent_losing_day():
    bars, now = short_up()
    lane, _, store, _ = build(bars, now)
    closed_trade(store, now - timedelta(minutes=50), now - timedelta(minutes=30), 0.90, 0.40, qty=3)   # -$153.90 today
    out = lane.step(force=True)
    assert len(trades(store)) == 1 and any("daily brake" in s for s in out["skips"]), out


def test_open_premium_is_capped_at_a_quarter_of_equity():
    bars, now = short_up()
    lane, _, store, _ = build(bars, now)
    store.lane_open(sa.LANE, "QQQ", now - timedelta(minutes=5), 0.80, 3, True, dict(PAY, fees_open=1.95, contract="QQQ X"))   # $240 open
    out = lane.step(force=True)
    assert len(trades(store)) == 1 and any("25% open" in s for s in out["skips"]), out


def test_drawdown_reads_the_deepest_drop_from_a_peak():
    bars, now = short_up()
    lane, _, store, _ = build(bars, now)
    closed_trade(store, now - timedelta(days=3), now - timedelta(days=3) + timedelta(minutes=9), 0.50, 1.50, qty=2)   # +$197.40
    closed_trade(store, now - timedelta(days=2), now - timedelta(days=2) + timedelta(minutes=9), 1.00, 0.10, qty=3)   # -$273.90
    d = sa.drawdown(trades(store), sa.START_EQUITY)
    assert d["peak_equity"] == 1197.4 and d["max_drawdown_pct"] == round(273.9 / 1197.4 * 100, 1)
    rep = lane.report(now)
    assert rep["account"]["start_equity"] == 1000 and rep["account"]["max_drawdown_pct"] == d["max_drawdown_pct"]
    assert any("never restarted" in r for r in rep["rules"])


def test_the_lane_shows_a_thousand_dollar_balance_as_its_capital():
    class Lanes:
        challenge = object()
        small = object()
    cap = lane_capital(None, Lanes())
    assert cap[sa.LANE]["amount"] == 1000.0 and cap[sa.LANE]["basis"] == "balance"
    class NoSmall:
        challenge = object()
    assert sa.LANE not in lane_capital(None, NoSmall())


def test_the_api_serves_the_account_behind_the_token():
    from fastapi.testclient import TestClient
    from optplat.api import create_app
    from optplat.broker import SimBroker
    from optplat.engine import EngineConfig, TradingEngine
    from optplat.marketdata import DemoDataProvider
    from optplat.orders import OrderManager
    from optplat.strategy import LiquidTrendStrategy
    store = Store(":memory:")
    manager = OrderManager(SimBroker(), store)
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig(enforce_market_hours=False))
    c = TestClient(create_app(manager, "t" * 24, engine, None))
    assert c.get("/api/small-account").status_code == 401
    body = c.get("/api/small-account", headers={"X-API-Token": "t" * 24}).json()
    assert body["account"]["equity"] == sa.START_EQUITY and body["account"]["settled_cash"] == sa.START_EQUITY
    assert body["fictional"] is True and body["rules"] and body["limitations"]
