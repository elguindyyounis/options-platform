import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from helpers import NOW
from optplat import optionlanes as ol
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, TradingEngine
from optplat.market_clock import NY
from optplat.marketdata import Bar, ChainRow, DemoDataProvider, MarketSnapshot
from optplat.models import OptionContract, Right
from optplat.orders import OrderManager
from optplat.postmortem import MIN_TRADES_FOR_PATTERN, digest, post_mortem
from optplat.scanner import session_day
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy
from test_shortterm import OPEN, bar, end_of, first_signal_prefix, series
from test_swing import after, first_signal, mk, pullback_rets

TOKEN = "t" * 24
H = {"X-API-Token": TOKEN}


class OptFeed(DemoDataProvider):
    """Demo chains and quotes, with bars set by the test and an override for any contract's quote."""
    def __init__(self, clock, bars=None, daily=None):
        super().__init__(clock=clock)
        self.bars, self.daily, self.override = bars or [], daily or {}, {}
        self.calls = {"intraday": 0, "window": 0}

    def intraday_bars(self, symbol):
        self.calls["intraday"] += 1
        return list(self.bars)

    def daily_bars(self, symbols, months=2):
        return {s: self.daily[s] for s in symbols if s in self.daily}

    def snapshot_window(self, symbol, *a, **k):
        self.calls["window"] += 1
        return super().snapshot_window(symbol, *a, **k)

    def quotes_for(self, contracts):
        out = []
        for q in super().quotes_for(contracts):
            ov = self.override.get(q.contract.occ_symbol.strip())
            out.append(replace(q, bid=ov[0], ask=ov[1]) if ov else q)
        return out


def make(params, bars=None, daily=None, now=None, calendar=None):
    box = [now or OPEN]
    prov = OptFeed(lambda: box[0], bars, daily)
    store = Store(":memory:")
    lane = ol.OptionLane(prov, store, params, ol.Feed(prov, lambda: box[0]), clock=lambda: box[0], calendar=calendar)
    return lane, prov, store, box


SHORT = replace(ol.SHORT_BASE, symbols=("SPY",), budget_usd=5000.0)


def short_up():
    bars = series()
    n = first_signal_prefix(bars)
    assert n is not None
    return bars[:n], end_of(bars, n)


def short_down():
    closes = [100 + 0.08 * i for i in range(14)] + [101.1 - 0.35 * i for i in range(1, 12)]
    bars = [bar(i, round(c, 4)) for i, c in enumerate(closes)]
    for n in range(12, len(bars) + 1):
        from optplat import shortterm as st
        r = st.read(bars[:n], end_of(bars, n))
        if r and ol.short_signal(r, ol.SHORT_AGGR) == "P":
            return bars[:n], end_of(bars, n)
    raise AssertionError("no bearish signal in the fixture")


def opened(lane, prov, store):
    return [t for t in store.lane_trades(lane.p.lane, True, 50)]


# ------------------------------------------------------------ choosing a contract
def row(strike, right=Right.CALL, bid=4.9, ask=5.1, oi=500, vol=100, days=40):
    return ChainRow(OptionContract("AAA", NOW.date() + timedelta(days=days), right, strike), bid, ask, vol, oi, 0.3)


def chain(*rows, spot=100.0):
    return MarketSnapshot("AAA", spot, (spot,) * 5, tuple(rows), NOW, "t", True, True)


def test_the_contract_nearest_the_aimed_strike_wins_and_puts_aim_below_spot():
    p = replace(ol.SWING_BASE, otm_pct=2.0)
    got = ol.pick_contract(chain(row(100), row(102), row(105)), Right.CALL, NOW, p)
    assert got.contract.strike == 102
    put = ol.pick_contract(chain(row(100, Right.PUT), row(98, Right.PUT), row(95, Right.PUT)), Right.PUT, NOW, p)
    assert put.contract.strike == 98


@pytest.mark.parametrize("kw", [
    {"bid": 0.0}, {"bid": 3.0, "ask": 5.0}, {"oi": 20}, {"vol": 2}, {"days": 5}, {"days": 90}, {"ask": 0.30, "bid": 0.28},
])
def test_a_contract_that_fails_any_quote_expiry_or_liquidity_limit_is_never_picked(kw):
    assert ol.pick_contract(chain(row(100, **kw)), Right.CALL, NOW, ol.SWING_BASE) is None


def test_a_strike_far_from_the_aim_and_the_wrong_right_are_refused():
    assert ol.pick_contract(chain(row(112)), Right.CALL, NOW, ol.SWING_BASE) is None
    assert ol.pick_contract(chain(row(100, Right.PUT)), Right.CALL, NOW, ol.SWING_BASE) is None


# ------------------------------------------------------------ short-term lane
def test_an_ema_vwap_cross_up_buys_one_call_filled_at_the_ask_with_the_signal_recorded():
    bars, now = short_up()
    lane, prov, store, box = make(SHORT, bars, now=now)
    out = lane.step(force=True)
    t = opened(lane, prov, store)
    assert len(t) == 1 and out["opened"][0]["right"] == "C"
    o = t[0]["open_payload"]
    assert o["right"] == "C" and t[0]["entry_price"] == o["ask"] and o["multiplier"] == 100 and o["kind"] == "short"
    assert o["fees_open"] == round(t[0]["quantity"] * 0.65, 2) and o["signal"]["direction"] == "up"
    assert o["dte"] >= SHORT.dte_min and t[0]["fictional"] == 1
    box[0] = now + timedelta(minutes=3)
    lane.step(force=True)
    assert len(opened(lane, prov, store)) == 1      # the same bar is judged once, and one position per name


def test_a_cross_down_buys_a_put_only_when_the_lane_may_trade_both_ways():
    bars, now = short_down()
    both, prov, store, _ = make(replace(ol.SHORT_AGGR, symbols=("SPY",), budget_usd=5000.0), bars, now=now)
    both.step(force=True)
    assert [t["open_payload"]["right"] for t in opened(both, prov, store)] == ["P"]
    long_only, prov2, store2, _ = make(replace(SHORT, both_ways=False), bars, now=now)
    long_only.step(force=True)
    assert opened(long_only, prov2, store2) == []


def test_no_entry_outside_the_entry_window_or_on_stale_bars():
    bars, now = short_up()
    late = datetime(2026, 11, 12, 15, 30, tzinfo=NY).astimezone(timezone.utc)
    lane, prov, store, _ = make(SHORT, bars, now=late)
    lane.step(force=True)
    assert opened(lane, prov, store) == []
    stale, prov2, store2, _ = make(SHORT, bars, now=now + timedelta(hours=1))
    stale.step(force=True)
    assert opened(stale, prov2, store2) == []


def open_one():
    bars, now = short_up()
    lane, prov, store, box = make(SHORT, bars, now=now)
    lane.step(force=True)
    t = opened(lane, prov, store)[0]
    return lane, prov, store, box, t, now


def test_premium_stop_closes_at_the_bid_and_writes_a_post_mortem():
    lane, prov, store, box, t, now = open_one()
    prov.override[t["open_payload"]["contract"]] = (t["entry_price"] * 0.5, t["entry_price"] * 0.55)
    box[0] = now + timedelta(minutes=10)
    out = lane.step(force=True)
    done = store.lane_trades(lane.p.lane, True, 5)[0]
    assert out["closed"] == [{"symbol": "SPY", "reason": "stop"}] and done["close_reason"] == "stop"
    assert done["exit_price"] == round(t["entry_price"] * 0.5, 10) or done["exit_price"] == pytest.approx(t["entry_price"] * 0.5)
    pm = done["close_payload"]["postmortem"]
    assert "STOPPED_QUICKLY" in pm["tags"] and pm["lessons"] and pm["try_next"] and done["close_payload"]["fees_close"] == round(t["quantity"] * 0.65, 2)


def test_premium_target_closes_at_the_bid():
    lane, prov, store, box, t, now = open_one()
    prov.override[t["open_payload"]["contract"]] = (t["entry_price"] * 1.7, t["entry_price"] * 1.75)
    box[0] = now + timedelta(minutes=10)
    lane.step(force=True)
    done = store.lane_trades(lane.p.lane, True, 5)[0]
    assert done["close_reason"] == "target" and "TARGET_HIT" in done["close_payload"]["postmortem"]["tags"]


def test_flat_by_close_and_carried_over_close_the_position():
    lane, prov, store, box, t, now = open_one()
    box[0] = datetime(2026, 11, 12, 15, 46, tzinfo=NY).astimezone(timezone.utc)
    lane.step(force=True)
    assert store.lane_trades(lane.p.lane, True, 5)[0]["close_reason"] == "flat_by_close"
    lane2, prov2, store2, box2, t2, now2 = open_one()
    box2[0] = now2 + timedelta(days=1)
    lane2.step(force=True)
    assert store2.lane_trades(lane2.p.lane, True, 5)[0]["close_reason"] == "carried_over"


def test_a_position_that_cannot_be_marked_stays_open_and_says_so():
    lane, prov, store, box, t, now = open_one()
    prov.quotes_for = lambda contracts: []                     # the feed has nothing for it
    box[0] = datetime(2026, 11, 12, 15, 46, tzinfo=NY).astimezone(timezone.utc)
    out = lane.step(force=True)
    assert store.lane_trades(lane.p.lane, True, 5)[0]["closed_at"] is None
    assert any("no usable quote" in e for e in out["errors"])


def test_a_failing_feed_never_raises_and_opens_nothing():
    lane, prov, store, _ = make(SHORT, [], now=OPEN + timedelta(hours=1))
    prov.intraday_bars = lambda s: (_ for _ in ()).throw(RuntimeError("down"))
    out = lane.step(force=True)
    assert opened(lane, prov, store) == [] and out["errors"]


def test_the_lane_is_throttled_and_a_name_that_would_cost_more_than_the_budget_is_skipped():
    bars, now = short_up()
    lane, prov, store, box = make(SHORT, bars, now=now)
    lane.step()
    assert lane.step().get("note") == "throttled"
    small, prov2, store2, _ = make(replace(SHORT, budget_usd=1.0), bars, now=now)
    out = small.step(force=True)
    assert opened(small, prov2, store2) == [] and any("costs more" in s for s in out["skips"])


def test_a_sector_cap_and_the_open_limit_hold():
    bars, now = short_up()
    lane, prov, store, _ = make(replace(SHORT, symbols=("SPY", "QQQ", "IWM"), max_per_sector=2, max_open=3), bars, now=now)
    out = lane.step(force=True)
    assert len(opened(lane, prov, store)) == 2 and out["skipped"] == 1     # all three are broad index funds: the third is refused
    lane2, prov2, store2, _ = make(replace(SHORT, symbols=("SPY", "XLF"), max_open=1), bars, now=now)
    lane2.step(force=True)
    assert len(opened(lane2, prov2, store2)) == 1


# ------------------------------------------------------------ the ledger arithmetic
def test_option_pnl_uses_the_multiplier_and_both_fees_and_open_trades_show_an_unrealised_figure():
    from optplat.shortterm import lane_report
    store = Store(":memory:")
    now = NOW
    tid = store.lane_open("x", "AAA", now, 5.0, 2, True, {"multiplier": 100, "fees_open": 1.3, "contract": "AAA C", "fee_per_contract": 0.65})
    store.lane_close(tid, now, 6.0, "target", {"fees_close": 1.3})
    open_id = store.lane_open("x", "BBB", now, 2.0, 1, True, {"multiplier": 100, "fees_open": 0.65, "fee_per_contract": 0.65})
    store.set_state(f"lane_mark:{open_id}", json.dumps({"bid": 2.5, "ask": 2.6, "at": now.isoformat()}))
    rep = lane_report(store, "x", True, now, rules=[], limitations=[], symbols=[], exit_text={})
    closed = next(t for t in rep["trades"] if t["status"] == "CLOSED")
    assert closed["pnl"] == pytest.approx((6.0 - 5.0) * 2 * 100 - 2.6) and closed["pnl_pct"] == pytest.approx(197.4 / 1000 * 100, abs=0.01)
    live = next(t for t in rep["trades"] if t["status"] == "OPEN")
    assert live["unrealized_pnl"] == pytest.approx((2.5 - 2.0) * 100 - 0.65 - 0.65) and rep["summary"]["unrealized_pnl"] == live["unrealized_pnl"]


def test_share_lane_numbers_are_unchanged_by_the_option_fields():
    from optplat.shortterm import lane_report
    store = Store(":memory:")
    tid = store.lane_open("s", "AAA", NOW, 100.0, 10, True, {})
    store.lane_close(tid, NOW, 101.0, "target", {})
    t = lane_report(store, "s", True, NOW, rules=[], limitations=[], symbols=[], exit_text={})["trades"][0]
    assert t["pnl"] == 10.0 and t["pnl_pct"] == 1.0 and t["unrealized_pnl"] is None and t["multiplier"] == 1


# ------------------------------------------------------------ swing lanes
def uptrend():
    bars = mk(pullback_rets())
    n = first_signal(bars)
    assert n is not None
    return {"AAPL": bars[:n]}, after(bars, n)


def test_a_pullback_buys_a_call_30_to_60_days_out_but_a_single_stock_needs_a_known_earnings_date():
    data, now = uptrend()
    p = replace(ol.SWING_BASE, symbols=("AAPL",), budget_usd=20000.0)
    blocked, prov, store, _ = make(p, daily=data, now=now)                       # no calendar: earnings unknown, fails closed
    out = blocked.step(force=True)
    assert opened(blocked, prov, store) == [] and out["skipped"] == 1
    free, prov2, store2, _ = make(replace(p, earnings_gate=False), daily=data, now=now)
    free.step(force=True)
    t = opened(free, prov2, store2)
    assert len(t) == 1 and t[0]["open_payload"]["right"] == "C" and 30 <= t[0]["open_payload"]["dte"] <= 60
    assert t[0]["open_payload"]["earnings_state"] == "UNKNOWN" and t[0]["open_payload"]["kind"] == "swing"


def test_the_aggressive_swing_lane_enters_without_the_trend_filter_and_records_the_earnings_state():
    data, now = uptrend()
    p = replace(ol.SWING_AGGR, symbols=("AAPL",), budget_usd=20000.0)
    lane, prov, store, _ = make(p, daily=data, now=now)
    lane.step(force=True)
    t = opened(lane, prov, store)
    assert len(t) == 1 and t[0]["open_payload"]["earnings_state"] == "UNKNOWN" and t[0]["open_payload"]["stop_pct"] == 50
    assert 14 <= t[0]["open_payload"]["dte"] <= 35


def test_a_bounce_in_a_downtrend_buys_a_put_only_in_the_aggressive_lane():
    import random
    rng = random.Random(5)
    rets = [-0.005 + 0.004 * rng.gauss(0, 1) for _ in range(62)] + [0.015] * 7 + [-0.014, -0.006, -0.004, -0.004]
    bars = mk(rets)
    from optplat import swing as sw
    hit = None
    for n in range(sw.MIN_BARS, len(bars) + 1):
        r = sw.read(bars[:n], after(bars, n))
        if r and ol.swing_signal(r, ol.SWING_AGGR) == "P":
            hit = n
            break
    assert hit is not None
    now = after(bars, hit)
    lane, prov, store, _ = make(replace(ol.SWING_AGGR, symbols=("AAPL",), budget_usd=20000.0), daily={"AAPL": bars[:hit]}, now=now)
    lane.step(force=True)
    assert [t["open_payload"]["right"] for t in opened(lane, prov, store)] == ["P"]
    base, prov2, store2, _ = make(replace(ol.SWING_BASE, symbols=("AAPL",), earnings_gate=False, budget_usd=20000.0), daily={"AAPL": bars[:hit]}, now=now)
    base.step(force=True)
    assert opened(base, prov2, store2) == []


def swing_open():
    data, now = uptrend()
    lane, prov, store, box = make(replace(ol.SWING_AGGR, symbols=("AAPL",), budget_usd=20000.0), daily=data, now=now)
    lane.step(force=True)
    return lane, prov, store, box, opened(lane, prov, store)[0], now, data


def test_swing_option_exits_expiry_near_time_and_trend_break():
    lane, prov, store, box, t, now, data = swing_open()
    exp = date.fromisoformat(t["open_payload"]["expiry"])
    prov.override[t["open_payload"]["contract"]] = (t["entry_price"], t["entry_price"] * 1.02)   # quiet premium: only the calendar acts
    box[0] = datetime.combine(exp - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15)
    lane.step(force=True)
    assert store.lane_trades(lane.p.lane, True, 3)[0]["close_reason"] == "expiry_near"
    lane, prov, store, box, t, now, data = swing_open()
    prov.override[t["open_payload"]["contract"]] = (t["entry_price"], t["entry_price"] * 1.02)
    box[0] = now + timedelta(days=10)                                   # past the 8-trading-day limit, contract still alive
    long_data = {"AAPL": data["AAPL"] + [Bar(data["AAPL"][-1].day + timedelta(days=k), data["AAPL"][-1].close, 1_000_000) for k in range(1, 13)]}
    prov.daily = long_data
    lane.feed._cache.clear()
    lane.step(force=True)
    assert store.lane_trades(lane.p.lane, True, 3)[0]["close_reason"] == "time"


def test_a_flow_signal_is_acted_on_only_when_open_interest_rose_the_read_is_clear_and_the_scan_is_current():
    now = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
    def fu(**kw):
        base = {"symbol": "AAPL", "contract": "AAPL  261218C00300000", "prior_day": "2026-11-11", "prior_volume": 800, "prior_oi": 40, "oi_change": 520,
                "oi_verdict": "OI_ROSE", "position_read": "BUY_TO_OPEN", "lean": "BULLISH", "prior_low_oi": True, "prior_ratio": 20.0, "sector": "Mega-cap tech"}
        return {**base, **kw}
    def run(follow_ups, session="2026-11-12", p=None):
        lane, prov, store, box = make(p or replace(ol.FLOW, budget_usd=20000.0), now=now)
        store.record_scan(now, True, {"as_of": now.isoformat(), "session_day": session, "follow_ups": follow_ups})
        lane.step(force=True)
        return lane, prov, store
    lane, prov, store = run([fu()])
    t = opened(lane, prov, store)
    assert len(t) == 1 and t[0]["open_payload"]["right"] == "C" and t[0]["open_payload"]["signal"]["position_read"] == "BUY_TO_OPEN"
    lane, prov, store = run([fu(lean="BEARISH", position_read="BUY_TO_OPEN")])
    assert opened(lane, prov, store)[0]["open_payload"]["right"] == "P"
    for bad in (fu(oi_verdict="OI_FLAT_OR_MIXED"), fu(lean="UNCLEAR"), fu(prior_low_oi=False, prior_ratio=3.5)):
        lane, prov, store = run([bad])
        assert opened(lane, prov, store) == []
    lane, prov, store = run([fu()], session="2026-11-11")                  # a scan from another session is not acted on
    assert opened(lane, prov, store) == []
    lane, prov, store = run([fu()])
    lane.step(force=True)
    assert len(opened(lane, prov, store)) == 1                              # the same follow-up is never acted on twice


# ------------------------------------------------------------ post-mortems
def trade(right="C", entry=5.0, qty=2, spread=4.0, oi=500, dte=8, kind="short", **extra):
    return {"symbol": "AAA", "entry_price": entry, "quantity": qty, "opened_at": datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc).isoformat(),
            "open_payload": {"right": right, "multiplier": 100, "fees_open": 1.3, "underlying_price": 100.0, "spread_pct": spread,
                             "open_interest": oi, "dte": dte, "kind": kind, "contract": "AAA C", **extra}}


def closed_at(h):
    return datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc) + timedelta(hours=h)


def test_a_loss_with_the_underlying_against_it_is_tagged_wrong_direction_and_stopped():
    pm = post_mortem(trade(), 3.0, "stop", closed_at(0.5), {"underlying": 98.0, "fees_close": 1.3, "spread_pct": 4.0})
    assert {"WRONG_DIRECTION", "STOPPED_QUICKLY"} <= set(pm["tags"]) and pm["net_pct"] < -39 and "Lost" in pm["headline"] and pm["underlying_move_pct"] == -2.0


def test_a_loss_with_the_underlying_in_favour_is_decay_or_spread_not_direction():
    pm = post_mortem(trade(), 4.8, "flat_by_close", closed_at(5), {"underlying": 100.4, "fees_close": 1.3, "spread_pct": 8.0})
    assert "RIGHT_DIRECTION_LOST_MONEY" in pm["tags"] and "WRONG_DIRECTION" not in pm["tags"] and "TIME_DECAY" in pm["tags"] and "SPREAD_ATE_GAIN" in pm["tags"]


def test_puts_are_judged_against_a_falling_underlying():
    pm = post_mortem(trade(right="P"), 7.5, "target", closed_at(3), {"underlying": 97.0, "fees_close": 1.3, "spread_pct": 3.0})
    assert "TARGET_HIT" in pm["tags"] and "Won" in pm["headline"] and "WRONG_DIRECTION" not in pm["tags"]


def test_thin_wide_earnings_and_big_win_tags():
    pm = post_mortem(trade(spread=14.0, oi=10, earnings_state="SOON", kind="swing"), 12.0, "target", closed_at(30), {"underlying": 110.0, "fees_close": 1.3, "spread_pct": 5.0})
    assert {"WIDE_SPREAD_ENTRY", "THIN_MARKET", "EARNINGS_GAMBLE", "BIG_WIN"} <= set(pm["tags"])


def test_the_digest_calls_a_cause_a_pattern_only_after_enough_trades():
    def closed(net, tag):
        return {"close_payload": {"postmortem": {"tags": [tag], "net_pct": net}}}
    few = digest([closed(-40, "STOPPED")] * (MIN_TRADES_FOR_PATTERN - 1) + [closed(30, "TARGET_HIT")])
    assert not any(r["pattern"] for r in few["tags"]) and few["trades_reviewed"] == MIN_TRADES_FOR_PATTERN
    many = digest([closed(-40, "STOPPED")] * MIN_TRADES_FOR_PATTERN)
    row_ = many["tags"][0]
    assert row_["tag"] == "STOPPED" and row_["pattern"] and row_["avg_net_pct"] == -40 and row_["win_rate_pct"] == 0 and row_["try_next"]
    assert digest([{"close_payload": None}, {"close_payload": {}}])["tags"] == []


# ------------------------------------------------------------ plumbing and safety
def test_two_lanes_reading_the_same_name_in_the_same_minute_make_one_request():
    bars, now = short_up()
    box = [now]
    prov = OptFeed(lambda: box[0], bars)
    feed = ol.Feed(prov, lambda: box[0])
    a = ol.OptionLane(prov, Store(":memory:"), SHORT, feed, clock=lambda: box[0])
    b = ol.OptionLane(prov, Store(":memory:"), replace(ol.SHORT_AGGR, symbols=("SPY",)), feed, clock=lambda: box[0])
    a.step(force=True)
    b.step(force=True)
    assert prov.calls["intraday"] == 1
    box[0] = now + timedelta(minutes=5)
    a.step(force=True)
    assert prov.calls["intraday"] == 2


def test_the_option_lane_code_has_no_order_path():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(ol))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported & {"orders", "broker", "risk", "engine", "strategy"}, imported
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not used & {"OrderManager", "place_order", "submit_order", "SimBroker", "RiskPolicy", "BrokerAdapter"}, used


@pytest.fixture
def client():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    with TestClient(create_app(manager, TOKEN, engine, None)) as c:
        yield c, engine


def test_the_option_lanes_are_off_by_default_and_the_endpoints_say_so(client):
    c, engine = client
    assert EngineConfig().option_lanes_enabled is False and engine.maybe_option_lanes() is None
    assert c.get("/api/optlanes").status_code == 401
    body = c.get("/api/optlanes", headers=H).json()
    assert body["enabled"] is False and body["fictional"] is True and len(body["lanes"]) == 6 and "digest" in body
    assert {l["lane"] for l in body["lanes"]} == {p.lane for p in ol.ALL_PARAMS}
    assert c.post("/api/optlanes/step", headers=H).status_code == 409


def test_switching_the_lanes_on_runs_them_and_every_trade_is_labelled_fictional_on_demo_data(client):
    c, engine = client
    engine.set_config({"option_lanes_enabled": True, "enforce_market_hours": False})
    res = c.post("/api/optlanes/step", headers=H).json()
    assert len(res["lanes"]) == 6 and all("errors" in x for x in res["lanes"])
    body = c.get("/api/optlanes", headers=H).json()
    assert body["enabled"] is True and all(l["fictional"] is True for l in body["lanes"])
    assert all(l["rules"] and l["limitations"] and l["params"] for l in body["lanes"])
    assert all(l["last_check"] and {"opened", "closed", "errors", "skips"} <= set(l["last_check"]) for l in body["lanes"])  # "why no trades?" is answerable
    for p in ol.ALL_PARAMS:
        for t in engine.store.lane_trades(p.lane, True, 100):
            assert t["fictional"] == 1


def test_the_lane_parameters_keep_the_aggressive_variants_larger_and_looser_than_the_base():
    assert ol.SHORT_AGGR.budget_usd > ol.SHORT_BASE.budget_usd and ol.SHORT_AGGR.dte_max < ol.SHORT_BASE.dte_max
    assert ol.SWING_AGGR.experimental and not ol.SWING_BASE.experimental and ol.SWING_AGGR.both_ways and not ol.SWING_BASE.both_ways
    assert ol.SWING_BASE.earnings_gate and not ol.SWING_AGGR.earnings_gate
    assert all(p.max_per_sector < p.max_open for p in ol.ALL_PARAMS)   # no single sector can fill a whole book
    assert ol.SWING_AGGR.budget_usd >= 4 * ol.SWING_BASE.budget_usd and ol.SHORT_AGGR.budget_usd >= 4 * ol.SHORT_BASE.budget_usd
    assert ol.SHORT_AGGR.stack == ol.SWING_AGGR.stack == "any" and ol.SHORT_BASE.stack == ol.SWING_BASE.stack == "none"


# ------------------------------------------------------------ stacking, size and liquidity
def seed(lane, store, sym, contract, entry):
    return store.lane_open(lane.p.lane, sym, OPEN, entry, 1, True, {"contract": contract, "right": "C", "expiry": "2026-12-18", "strike": 100.0,
                                                                   "stop_pct": 40, "target_pct": 100, "multiplier": 100})


@pytest.mark.parametrize("stack,marks_bid,expected", [
    ("none", 3.0, False), ("any", 1.0, True), ("winners", 3.0, True), ("winners", 1.0, False), ("winners", None, False),
])
def test_stack_rules_decide_whether_a_second_position_in_a_name_may_open(stack, marks_bid, expected):
    p = replace(ol.SHORT_AGGR, symbols=("SPY",), stack=stack, max_per_name=2)
    lane, prov, store, _ = make(p)
    seed(lane, store, "SPY", "SPY C1", 2.0)
    marks = {} if marks_bid is None else {"SPY C1": (marks_bid, marks_bid + 0.1)}
    assert lane._may_open("SPY", lane._held(), marks) is expected


def test_the_name_limit_book_limit_and_sector_limit_still_hold_when_stacking_is_on():
    p = replace(ol.SHORT_AGGR, stack="any", max_per_name=2, max_open=3, max_per_sector=2)
    lane, prov, store, _ = make(p)
    seed(lane, store, "SPY", "A", 2.0)
    seed(lane, store, "SPY", "B", 2.0)
    assert lane._may_open("SPY", lane._held(), {}) is False                 # two in the name already
    assert lane._may_open("QQQ", lane._held(), {}) is False                 # same sector, and the sector holds two
    assert lane._may_open("AAPL", lane._held(), {}) is True
    seed(lane, store, "AAPL", "C", 2.0)
    assert lane._may_open("MSFT", lane._held(), {}) is False                # the book is full


def test_a_stacked_entry_records_what_it_was_stacked_on_and_is_tagged_in_its_post_mortem():
    bars, now = short_up()
    lane, prov, store, box = make(replace(SHORT, stack="any", max_per_name=2), bars, now=now)
    lane.step(force=True)
    held = lane._held()
    first = held[0]
    made = lane._enter("SPY", "C", now, lane._new_out(now), {"close": 100.0}, held)
    assert made["open_payload"]["stack_index"] == 1 and made["open_payload"]["stacked_on"] == [first["id"]]
    assert len(lane._held()) == 2
    pm = post_mortem({**made, "opened_at": now.isoformat()}, 1.0, "stop", now + timedelta(hours=1), {"underlying": 99.0})
    assert "STACKED" in pm["tags"]


def test_an_oversized_trade_is_tagged_so_the_result_is_read_as_optimistic():
    t = trade(size_vs_volume_pct=35.0)
    assert "OVERSIZED_FOR_LIQUIDITY" in post_mortem(t, 6.0, "target", closed_at(1), {"underlying": 101.0})["tags"]
    assert "OVERSIZED_FOR_LIQUIDITY" in post_mortem(trade(size_vs_oi_pct=8.0), 6.0, "target", closed_at(1), {"underlying": 101.0})["tags"]
    assert "OVERSIZED_FOR_LIQUIDITY" not in post_mortem(trade(size_vs_volume_pct=2.0), 6.0, "target", closed_at(1), {"underlying": 101.0})["tags"]


def test_entries_record_their_size_against_the_contract_and_the_flow_lane_doubles_on_a_thin_contract():
    now = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
    def qty_for(low_oi):
        lane, prov, store, _ = make(replace(ol.FLOW, budget_usd=20000.0), now=now)
        f = {"symbol": "AAPL", "contract": "AAPL  261218C00300000", "prior_day": "2026-11-11", "prior_volume": 800, "prior_oi": 40, "oi_change": 520,
             "oi_verdict": "OI_ROSE", "position_read": "BUY_TO_OPEN", "lean": "BULLISH", "prior_low_oi": low_oi, "prior_ratio": 20.0, "sector": "Mega-cap tech"}
        store.record_scan(now, True, {"as_of": now.isoformat(), "session_day": "2026-11-12", "follow_ups": [f]})
        lane.step(force=True)
        t = store.lane_trades(lane.p.lane, True, 5)[0]
        assert t["open_payload"]["size_vs_volume_pct"] is not None and t["open_payload"]["signal"]["conviction_mult"] == (2.0 if low_oi else 1.0)
        return t["quantity"], t["open_payload"]["budget_usd"]
    (q1, b1), (q2, b2) = qty_for(False), qty_for(True)
    assert b2 == 2 * b1 and q2 >= 2 * q1 - 1


def test_a_lane_remembers_what_its_last_check_did_and_why_it_did_not_trade():
    now = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
    lane, prov, store, _ = make(replace(ol.FLOW, budget_usd=20000.0), now=now)
    lane.step(force=True)  # no scan results exist, so the flow lane has nothing to act on
    saved = json.loads(store.get_state(f"optlane_last_result:{lane.p.lane}", ""))
    assert saved["opened"] == 0 and saved["at"] == now.isoformat() and "errors" in saved and "skips" in saved


def test_frozen_baseline_is_pinned_and_independent():
    """Challenge 3: the yardstick lane must never drift. Changing its settings is an owner decision (new lane id, new fingerprint)."""
    assert ol.params_fingerprint(ol.FROZEN_BASELINE) == ol.FROZEN_FINGERPRINT
    assert ol.FROZEN_BASELINE in ol.ALL_PARAMS
    assert len({p.lane for p in ol.ALL_PARAMS}) == len(ol.ALL_PARAMS)
    # It is the first short-term rule at the base size, and no looser than the base lane it mirrors.
    b = ol.SHORT_BASE
    f = ol.FROZEN_BASELINE
    assert (f.kind, f.budget_usd, f.max_open, f.stack, f.max_per_name) == ("short", 1000, 4, "none", 1)
    assert f.experimental is False and f.budget_usd <= ol.SHORT_AGGR.budget_usd
    assert f.max_per_sector < f.max_open and b.lane != f.lane


# ------------------------------------------------------------ stressed lane P&L (shown beside, never instead of, the bid exit)
def test_lane_summary_shows_realized_pnl_with_the_stressed_exit_beside_the_bid_exit():
    from optplat.shortterm import lane_report
    store = Store(":memory:")
    pay = {"multiplier": 100, "fees_open": 1.3, "contract": "AAA C"}
    a = store.lane_open("x", "AAA", NOW, 5.0, 2, True, dict(pay))
    store.lane_close(a, NOW, 6.0, "target", {"fees_close": 1.3, "postmortem": {"stress_concession_pct": 10.0}})
    b = store.lane_open("x", "BBB", NOW, 5.0, 1, True, dict(pay))
    store.lane_close(b, NOW, 4.0, "stop", {"fees_close": 1.3})  # no post-mortem: unknown, not zero concession
    sm = lane_report(store, "x", True, NOW, rules=[], limitations=[], symbols=[], exit_text={})["summary"]
    # stressed price 6.0 * 0.9 = 5.4 -> (5.4 - 5.0) * 2 * 100 - 2.6
    assert sm["stress_realized_pnl"] == pytest.approx(77.4) and sm["stress_trades"] == 1
    assert sm["stress_basis_realized_pnl"] == pytest.approx(197.4) and sm["stress_realized_pnl"] < sm["stress_basis_realized_pnl"]
    assert sm["realized_pnl"] == pytest.approx(197.4 + (4.0 - 5.0) * 100 - 2.6)  # headline figure itself is unchanged
    t = {x["symbol"]: x for x in lane_report(store, "x", True, NOW, rules=[], limitations=[], symbols=[], exit_text={})["trades"]}
    assert t["AAA"]["stress_pnl"] == pytest.approx(77.4) and t["BBB"]["stress_pnl"] is None


def test_lane_without_postmortems_has_no_stress_figure_and_share_lanes_are_untouched():
    from optplat.shortterm import lane_report
    store = Store(":memory:")
    tid = store.lane_open("s", "AAA", NOW, 100.0, 10, True, {})
    store.lane_close(tid, NOW, 101.0, "target", {})
    sm = lane_report(store, "s", True, NOW, rules=[], limitations=[], symbols=[], exit_text={})["summary"]
    assert sm["stress_realized_pnl"] is None and sm["stress_trades"] == 0 and sm["realized_pnl"] == 10.0
