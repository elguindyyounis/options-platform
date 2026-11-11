import random
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from optplat import swing as sw
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, TradingEngine
from optplat.events import EventCalendar
from optplat.marketdata import Bar, DemoDataProvider, MarketDataProvider
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy

TOKEN = "t" * 24
H = {"X-API-Token": TOKEN}


def mk(rets, start=100.0, d0=date(2026, 6, 1), vol=1_000_000):
    out, p, d = [], start, d0
    for r in rets:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        p *= 1 + r
        out.append(Bar(d, round(p, 4), vol))
        d += timedelta(days=1)
    return out


def pullback_rets(seed=3):
    rng = random.Random(seed)
    return [0.005 + 0.004 * rng.gauss(0, 1) for _ in range(62)] + [-0.012, -0.012, -0.011, -0.01, -0.008] + [0.014, 0.006, 0.004, 0.004]


def after(bars, n):
    """A moment after bar n-1 closed, so that bar counts as completed."""
    return datetime.combine(bars[n - 1].day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)


def first_signal(bars):
    for n in range(sw.MIN_BARS, len(bars) + 1):
        r = sw.read(bars[:n], after(bars, n))
        if r and sw.entry_signal(r):
            return n
    return None


class Feed(MarketDataProvider):
    name, fictional = "feed", True

    def __init__(self, data=None, boom=False):
        self.data, self.boom = data or {}, boom

    def snapshot(self, symbol):  # pragma: no cover
        raise NotImplementedError

    def quotes_for(self, contracts):  # pragma: no cover
        return []

    def daily_bars(self, symbols, months=2):
        if self.boom:
            raise RuntimeError("feed down")
        return {s: self.data[s] for s in symbols if s in self.data}


def lane(feed, now_box, symbols=("SPY",), calendar=None):
    return sw.SwingLane(feed, Store(":memory:"), clock=lambda: now_box[0], symbols=symbols, calendar=calendar)


# ------------------------------------------------------------ indicators and the rule
def test_too_little_history_is_not_read():
    bars = mk(pullback_rets())
    assert sw.read(bars[: sw.MIN_BARS - 1], after(bars, sw.MIN_BARS - 1)) is None
    assert sw.read([], datetime(2026, 9, 1, tzinfo=timezone.utc)) is None


def test_the_pullback_fixture_signals_and_each_condition_matters():
    bars = mk(pullback_rets())
    n = first_signal(bars)
    assert n is not None
    r = sw.read(bars[:n], after(bars, n))
    assert r["rsi_dip"] <= sw.RSI_DIP and r["rsi"] > r["rsi_prev"] and r["sma_fast"] > r["sma_slow"]
    assert not sw.entry_signal({**r, "close": r["sma_slow"] - 0.01})           # trend broken
    assert not sw.entry_signal({**r, "rsi_dip": sw.RSI_DIP + 5})               # no pullback happened
    assert not sw.entry_signal({**r, "rsi": r["rsi_prev"] - 1})                # still falling
    assert not sw.entry_signal({**r, "day_move_pct": sw.MAX_DAY_MOVE_PCT + 1})  # a news jump, not a pullback ending
    assert not sw.entry_signal({**r, "sma_fast": r["sma_slow"] - 1})           # downtrend


def test_todays_unfinished_bar_is_never_used_while_the_session_is_open():
    bars = mk(pullback_rets())
    n = first_signal(bars)
    # judged on the same ET day as the last bar, during the session: that bar is partial and must be dropped
    noon_et = datetime.combine(bars[n - 1].day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=17)
    r = sw.read(bars[:n], noon_et)
    assert r is None or r["day"] < bars[n - 1].day


def test_stop_distance_is_bounded():
    assert sw.stop_distance_pct(0.0001) == sw.STOP_MIN_PCT and sw.stop_distance_pct(0.5) == sw.STOP_MAX_PCT


# ------------------------------------------------------------ the lane
def test_it_enters_once_and_stores_its_own_stop_and_target():
    bars = mk(pullback_rets())
    n = first_signal(bars)
    now = [after(bars, n)]
    ln = lane(Feed({"SPY": bars[:n]}), now)
    out = ln.step()
    assert out["opened"] == [{"symbol": "SPY"}]
    t = ln.store.lane_trades(sw.LANE, True)[0]
    p = t["open_payload"]
    assert t["quantity"] == int(sw.NOTIONAL_USD // t["entry_price"]) and t["entry_price"] > bars[n - 1].close
    assert p["stop"] < t["entry_price"] < p["target"] and p["max_hold_bars"] == sw.MAX_HOLD_BARS
    assert (p["target"] / t["entry_price"] - 1) == pytest.approx(sw.TARGET_R * (1 - p["stop"] / t["entry_price"]), rel=0.02)
    now[0] += timedelta(hours=2)
    assert ln.step()["opened"] == []  # an open name is never doubled up


def test_it_is_throttled_unless_forced():
    bars = mk(pullback_rets())
    n = first_signal(bars)
    now = [after(bars, n)]
    ln = lane(Feed({"SPY": bars[:n]}), now)
    ln.step()
    now[0] += timedelta(minutes=10)
    assert ln.step()["note"] == "throttled"
    assert "note" not in ln.step(force=True)


def test_a_failing_or_empty_feed_means_no_entry_and_says_why():
    now = [datetime(2026, 9, 5, tzinfo=timezone.utc)]
    down = lane(Feed(boom=True), now).step()
    assert down["opened"] == [] and "feed down" in down["errors"][0]
    assert lane(Feed({}), now).step()["opened"] == []


def test_single_stocks_need_a_known_earnings_date_with_none_in_the_way():
    bars = mk(pullback_rets())
    n = first_signal(bars)
    now = [after(bars, n)]
    feed = Feed({"NVDA": bars[:n]})
    assert lane(feed, now, ("NVDA",)).step()["opened"] == []  # no calendar: not allowed
    unknown = EventCalendar(earnings_source=lambda s: None, clock=lambda: now[0])
    assert lane(feed, now, ("NVDA",), unknown).step()["opened"] == []  # unknown date: not allowed
    soon = EventCalendar(earnings_source=lambda s: [now[0].date() + timedelta(days=6)], clock=lambda: now[0])
    ln = lane(feed, now, ("NVDA",), soon)
    out = ln.step()
    assert out["opened"] == [] and out["skipped"] == 1
    far = EventCalendar(earnings_source=lambda s: [now[0].date() + timedelta(days=90)], clock=lambda: now[0])
    assert lane(feed, now, ("NVDA",), far).step()["opened"] == [{"symbol": "NVDA"}]
    assert lane(Feed({"SPY": bars[:n]}), now, ("SPY",)).step()["opened"] == [{"symbol": "SPY"}]  # a fund needs no earnings date


def _opened(extra_rets):
    bars = mk(pullback_rets())
    n = first_signal(bars)
    now = [after(bars, n)]
    feed = Feed({"SPY": bars[:n]})
    ln = lane(feed, now)
    ln.step()
    cont = mk(pullback_rets() + extra_rets)
    feed.data["SPY"] = cont
    now[0] = after(cont, len(cont)) + timedelta(hours=2)
    return ln, ln.step(), cont


def test_exits_on_stop_target_and_time():
    ln, out, _ = _opened([-0.06])
    assert out["closed"] == [{"symbol": "SPY", "reason": "stop"}]
    t = ln.store.lane_trades(sw.LANE, True)[0]
    assert t["exit_price"] < t["entry_price"] and t["closed_at"]
    assert _opened([0.03, 0.03, 0.03])[1]["closed"] == [{"symbol": "SPY", "reason": "target"}]
    assert _opened([0.0005] * sw.MAX_HOLD_BARS)[1]["closed"] == [{"symbol": "SPY", "reason": "time"}]
    assert _opened([0.0005])[1]["closed"] == []  # a quiet day exits nothing


def test_a_close_under_the_slow_average_but_above_the_stop_is_a_trend_break():
    bars = mk(pullback_rets())
    n = first_signal(bars)
    probe = lane(Feed({"SPY": bars[:n]}), [after(bars, n)])
    probe.step()
    stop = probe.store.lane_trades(sw.LANE, True)[0]["open_payload"]["stop"]
    found = None
    for pct in range(1, 100):
        cont = mk(pullback_rets() + [-pct / 1000])
        r = sw.read(cont, after(cont, len(cont)))
        if r["close"] < r["sma_slow"] and r["close"] > stop:
            found = pct
            break
    assert found is not None
    ln, out, _ = _opened([-found / 1000])
    assert out["closed"] == [{"symbol": "SPY", "reason": "trend_break"}]


# ------------------------------------------------------------ report, engine, api
def test_report_uses_the_swing_ledger_only():
    store = Store(":memory:")
    now = datetime(2026, 11, 12, tzinfo=timezone.utc)
    a = store.lane_open(sw.LANE, "SPY", now, 100.0, 10, True, {"stop": 95, "target": 107})
    store.lane_close(a, now, 104.0, "target", {})
    store.lane_open("shortterm-ema9-vwap", "QQQ", now, 50.0, 10, True, {})
    rep = sw.build_report(store, True, now)
    assert rep["lane"] == sw.LANE and rep["summary"]["total"] == 1 and rep["summary"]["realized_pnl"] == 40.0
    assert rep["trades"][0]["close_text"] == sw.EXIT_TEXT["target"] and rep["rules"] and rep["limitations"]


def test_the_lane_is_off_by_default_and_never_raises_into_the_loop():
    assert EngineConfig().swing_enabled is False
    engine = TradingEngine(OrderManager(SimBroker(), Store(":memory:")), Feed(boom=True), LiquidTrendStrategy(), default_config=EngineConfig())
    assert engine.maybe_swing() is None
    engine.set_config({"swing_enabled": True})
    out = engine.maybe_swing()
    assert out is not None and out["opened"] == [] and out["errors"]


def test_demo_daily_bars_cover_a_swing_lookback():
    p = DemoDataProvider(clock=lambda: datetime(2026, 11, 12, tzinfo=timezone.utc))
    assert len(p.daily_bars(["SPY"])["SPY"]) == 30  # the scanner's default is unchanged
    assert len(p.daily_bars(["SPY"], months=sw.BARS_MONTHS)["SPY"]) >= sw.MIN_BARS


@pytest.fixture
def client():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    with TestClient(create_app(manager, TOKEN, engine)) as c:
        yield c


def test_api_requires_the_token_and_refuses_a_step_while_off(client):
    assert client.get("/api/swing").status_code == 401 and client.post("/api/swing/step").status_code == 401
    body = client.get("/api/swing", headers=H).json()
    assert body["enabled"] is False and body["fictional"] is True and body["trades"] == [] and body["rules"]
    assert client.post("/api/swing/step", headers=H).status_code == 409
    assert client.put("/api/engine/config", headers=H, json={"swing_enabled": True}).status_code == 200
    assert client.post("/api/swing/step", headers=H).status_code == 200
    assert client.get("/api/swing", headers=H).json()["enabled"] is True
