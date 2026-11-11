from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from optplat import shortterm as st
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, TradingEngine
from optplat.market_clock import NY
from optplat.marketdata import DemoDataProvider, IntradayBar, MarketDataProvider
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy

TOKEN = "t" * 24
H = {"X-API-Token": TOKEN}
OPEN = datetime(2026, 11, 12, 9, 30, tzinfo=NY).astimezone(timezone.utc)  # a Thursday, regular session


def bar(i, close, vol=10_000.0, day_open=OPEN):
    return IntradayBar(day_open + timedelta(minutes=5 * i), close, close * 1.001, close * 0.999, close, vol)


def series(extra=()):
    """A decline for 14 bars, then a rise: the 9-bar EMA crosses above VWAP somewhere in the rise."""
    closes = [100 - 0.08 * i for i in range(14)] + [98.9 + 0.35 * i for i in range(1, 12)] + list(extra)
    return [bar(i, round(c, 4)) for i, c in enumerate(closes)]


def end_of(bars, n, minutes=1):
    return bars[n - 1].ts + timedelta(minutes=5 + minutes)


def first_signal_prefix(bars):
    for n in range(st.MIN_BARS, len(bars) + 1):
        r = st.read(bars[:n], end_of(bars, n))
        if r and st.entry_signal(r):
            return n
    return None


class Feed(MarketDataProvider):
    name, fictional = "feed", True

    def __init__(self, bars=None, boom=False):
        self.bars, self.boom = bars or [], boom

    def snapshot(self, symbol):  # pragma: no cover - not used
        raise NotImplementedError

    def quotes_for(self, contracts):  # pragma: no cover - not used
        return []

    def intraday_bars(self, symbol):
        if self.boom:
            raise RuntimeError("feed down")
        return list(self.bars)


def lane(feed, now_box, symbols=("SPY",)):
    return st.ShortTermLane(feed, Store(":memory:"), clock=lambda: now_box[0], symbols=symbols)


# ------------------------------------------------------------ indicators
def test_ema_follows_the_standard_recurrence_and_vwap_needs_volume():
    assert st.ema([10, 10, 10], 9) == [10, 10, 10]
    e = st.ema([10, 20], 9)
    assert e[1] == pytest.approx(10 + 0.2 * 10)
    zero = [bar(i, 100, vol=0.0) for i in range(14)]
    assert st.read(zero, end_of(zero, 14)) is None  # no volume: VWAP is undefined, so nothing is read


def test_too_few_bars_and_unfinished_bars_are_not_read():
    bars = series()
    assert st.read(bars[: st.MIN_BARS - 1], end_of(bars, st.MIN_BARS - 1)) is None
    n = st.MIN_BARS + 3
    # the last bar has not closed yet at this moment, so it must not be used
    r = st.read(bars[:n], bars[n - 1].ts + timedelta(minutes=2))
    assert r is not None and r["bar_ts"] == bars[n - 2].ts


def test_a_crossing_exists_in_the_fixture_and_requires_close_above_vwap():
    bars = series()
    n = first_signal_prefix(bars)
    assert n is not None
    r = st.read(bars[:n], end_of(bars, n))
    assert r["prev_ema"] <= r["prev_vwap"] and r["ema"] > r["vwap"] and r["close"] > r["vwap"]
    assert not st.entry_signal({**r, "close": r["vwap"] - 0.01})


# ------------------------------------------------------------ the lane
def test_it_enters_once_on_the_signal_bar_and_records_why():
    bars = series()
    n = first_signal_prefix(bars)
    now = [end_of(bars, n)]
    feed = Feed(bars[:n])
    ln = lane(feed, now)
    out = ln.step()
    assert out["opened"] == [{"symbol": "SPY"}] and out["errors"] == []
    t = ln.store.lane_trades(st.LANE, True)[0]
    assert t["quantity"] == int(st.NOTIONAL_USD // t["entry_price"]) and t["entry_price"] > bars[n - 1].close  # slippage against us
    assert set(t["open_payload"]) >= {"bar", "ema", "vwap", "prev_ema", "prev_vwap", "bars"}
    assert ln.step()["opened"] == []  # an open symbol is never doubled up


def test_no_entry_outside_the_window_or_on_stale_data_or_when_the_feed_fails():
    bars = series()
    n = first_signal_prefix(bars)
    assert n is not None
    ny = lambda h, m: datetime(2026, 11, 12, h, m, tzinfo=NY).astimezone(timezone.utc)  # noqa: E731
    assert [st.in_entry_window(ny(h, m)) for h, m in ((9, 55), (10, 0), (15, 0), (15, 1))] == [False, True, True, False]
    assert st.ENTRY_UNTIL < st.FLAT_BY  # entries stop well before the flat time
    stale = lane(Feed(bars[:n]), [end_of(bars, n, minutes=st.MAX_BAR_AGE_S // 60 + 5)])
    assert stale.step()["opened"] == []
    down = lane(Feed(boom=True), [end_of(bars, n)])
    out = down.step()
    assert out["opened"] == [] and "feed down" in out["errors"][0]
    empty = lane(Feed([]), [end_of(bars, n)])
    assert empty.step()["opened"] == []  # an empty feed reads as unknown, never as a signal


def test_it_exits_below_vwap_at_the_stop_and_flat_by_the_close():
    bars = series()
    n = first_signal_prefix(bars)
    now = [end_of(bars, n)]
    feed = Feed(bars[:n])
    ln = lane(feed, now)
    ln.step()
    # price collapses: closes below VWAP, and far enough to hit the stop
    feed.bars = bars[:n] + [bar(n, bars[n - 1].close * 0.98)]
    now[0] = end_of(feed.bars, n + 1)
    out = ln.step()
    assert out["closed"] and out["closed"][0]["reason"] in ("stop", "below_vwap")
    t = ln.store.lane_trades(st.LANE, True)[0]
    assert t["closed_at"] and t["exit_price"] < t["entry_price"]

    # a second lane: held into the close with price drifting up is closed flat by 15:45
    ln2 = lane(Feed(bars[:n]), [end_of(bars, n)])
    ln2.step()
    late_bars = bars[:n] + [bar(i, bars[n - 1].close * 1.001) for i in range(n, 75)]
    ln2.provider.bars = late_bars
    ln2.clock = lambda: datetime(2026, 11, 12, 15, 46, tzinfo=NY).astimezone(timezone.utc)
    assert ln2.step()["closed"][0]["reason"] == "flat_by_close"


def test_a_trade_left_from_an_earlier_day_is_closed_not_carried():
    bars = series()
    n = first_signal_prefix(bars)
    ln = lane(Feed(bars[:n]), [end_of(bars, n)])
    ln.store.lane_open(st.LANE, "SPY", end_of(bars, n) - timedelta(days=1), 100.0, 5, True, {})
    out = ln.step()
    assert out["closed"] == [{"symbol": "SPY", "reason": "carried_over"}]


def test_at_most_max_open_positions():
    bars = series()
    n = first_signal_prefix(bars)
    syms = ("SPY", "QQQ", "IWM", "AAPL", "NVDA")
    ln = lane(Feed(bars[:n]), [end_of(bars, n)], symbols=syms)
    out = ln.step()
    assert len(out["opened"]) == st.MAX_OPEN


# ------------------------------------------------------------ report, engine, api
def test_report_computes_profit_and_labels_unfinished_trades():
    store = Store(":memory:")
    now = datetime(2026, 11, 12, 18, 0, tzinfo=timezone.utc)
    a = store.lane_open(st.LANE, "SPY", now, 100.0, 10, True, {})
    store.lane_close(a, now, 101.0, "target", {})
    b = store.lane_open(st.LANE, "QQQ", now, 50.0, 10, True, {})
    store.lane_close(b, now, 49.0, "stop", {})
    store.lane_open(st.LANE, "IWM", now, 20.0, 10, True, {})
    store.lane_open(st.LANE, "REAL", now, 20.0, 10, False, {})  # a real-data row must not leak into a fictional view
    rep = st.build_report(store, True, now)
    s = rep["summary"]
    assert s["total"] == 3 and s["closed"] == 2 and s["open"] == 1 and s["wins"] == 1 and s["win_rate_pct"] == 50.0
    assert s["realized_pnl"] == 0.0 and rep["limitations"] and rep["rules"]
    assert [t["pnl"] for t in rep["trades"] if t["status"] == "OPEN"] == [None]
    assert store.lane_close(a, now, 5.0, "x", {}) is False  # a closed trade is never rewritten


def test_the_lane_is_off_by_default_and_never_raises_into_the_loop():
    assert EngineConfig().shortterm_enabled is False
    engine = TradingEngine(OrderManager(SimBroker(), Store(":memory:")), Feed(boom=True), LiquidTrendStrategy(), default_config=EngineConfig())
    assert engine.maybe_shortterm() is None
    engine.set_config({"shortterm_enabled": True, "enforce_market_hours": False})
    out = engine.maybe_shortterm()  # a failing feed is reported inside the result, not raised
    assert out is not None and out["opened"] == [] and len(out["errors"]) == len(st.LANE_SYMBOLS)
    with pytest.raises(ValueError):
        EngineConfig.from_dict({"shortterm_enabled": "yes"})


def test_demo_intraday_bars_are_ordered_deterministic_and_completed_only():
    now = datetime(2026, 11, 12, 17, 3, tzinfo=timezone.utc)
    p = DemoDataProvider(clock=lambda: now)
    a, b = p.intraday_bars("SPY"), p.intraday_bars("SPY")
    assert a == b and a and all(x.ts < y.ts for x, y in zip(a, a[1:]))
    assert all(x.ts + timedelta(minutes=5) <= now for x in a)


@pytest.fixture
def client():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    with TestClient(create_app(manager, TOKEN, engine)) as c:
        yield c, engine


def test_api_requires_the_token_reports_rules_and_refuses_a_step_while_off(client):
    c, engine = client
    assert c.get("/api/shortterm").status_code == 401 and c.post("/api/shortterm/step").status_code == 401
    body = c.get("/api/shortterm", headers=H).json()
    assert body["enabled"] is False and body["fictional"] is True and body["trades"] == [] and body["rules"]
    assert c.post("/api/shortterm/step", headers=H).status_code == 409
    assert c.put("/api/engine/config", headers=H, json={"shortterm_enabled": True, "enforce_market_hours": False}).status_code == 200
    assert c.post("/api/shortterm/step", headers=H).status_code == 200
    assert c.get("/api/shortterm", headers=H).json()["enabled"] is True
