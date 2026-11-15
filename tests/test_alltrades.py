from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from optplat import shortterm as st_mod
from optplat import swing as sw_mod
from optplat.alltrades import build_all
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.contracts import contract_label, parse_occ
from optplat.engine import EngineConfig, TradingEngine
from optplat.marketdata import DemoDataProvider
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy

TOKEN = "t" * 24
H = {"X-API-Token": TOKEN}
T0 = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
OCC = "SPY   261211P00751000"


@pytest.fixture
def parts():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    return manager, engine


def opt_payload(**kw):
    return {"contract": OCC, "right": "P", "strike": 751.0, "expiry": "2026-12-11", "multiplier": 100, "fees_open": 0.65, **kw}


def seed(store):
    a = store.lane_open("swing-options-base", "SPY", T0, 2.0, 2, True, opt_payload())
    store.lane_close(a, T0 + timedelta(hours=5), 3.0, "target", {"fees_close": 0.65})
    store.lane_open("flow-options", "NVDA", T0, 1.0, 1, True, opt_payload(contract="NVDA  261218C00200000", right="C", strike=200.0, expiry="2026-12-18"))
    s = store.lane_open(sw_mod.LANE, "AAPL", T0, 100.0, 5, True, {"rsi": 30})
    store.lane_close(s, T0 + timedelta(days=2), 90.0, "stop", {})
    store.lane_open(st_mod.LANE, "QQQ", T0 + timedelta(minutes=1), 400.0, 1, True, {})


def test_the_occ_symbol_is_read_into_name_side_strike_and_expiry():
    p = parse_occ(OCC)
    assert p == {"symbol": "SPY", "expiry": "2026-12-11", "right": "P", "strike": 751.0}
    assert contract_label(p["symbol"], p["right"], p["strike"], p["expiry"]) == "SPY put 751 · Dec 11 2026"
    assert parse_occ("SPY261218C00600500")["strike"] == 600.5
    assert parse_occ("garbage") is None and parse_occ(None) is None and parse_occ("SPY   261399C00100000") is None


def test_every_lane_appears_once_with_instrument_label_and_the_right_profit(parts):
    manager, engine = parts
    seed(engine.store)
    out = build_all(manager, engine.store, True, T0 + timedelta(days=3), engine.option_lanes)
    rows = {r["key"]: r for r in out["trades"]}
    assert len(rows) == len(out["trades"]) == 4
    opt = next(r for r in out["trades"] if r["source"] == "swing-options-base")
    assert opt["instrument"] == "options" and opt["label"] == "SPY put 751 · Dec 11 2026" and opt["right"] == "P"
    assert opt["pnl"] == round((3.0 - 2.0) * 2 * 100 - 0.65 - 0.65, 2) and opt["status"] == "CLOSED" and opt["held_seconds"] == 5 * 3600
    sh = next(r for r in out["trades"] if r["source"] == sw_mod.LANE)
    assert sh["instrument"] == "shares" and sh["label"] == "AAPL" and sh["pnl"] == -50.0 and sh["right"] is None
    o, s = out["summary"]["options"], out["summary"]["shares"]
    assert (o["total"], s["total"], out["summary"]["all"]["total"]) == (2, 2, 4)
    assert o["closed"] == 1 and o["wins"] == 1 and s["closed"] == 1 and s["wins"] == 0
    assert {x["source"] for x in out["sources"]} >= {"swing-options-base", "flow-options", sw_mod.LANE, st_mod.LANE}
    assert [r["opened_at"] for r in out["trades"]] == sorted((r["opened_at"] for r in out["trades"]), reverse=True)


def test_an_open_trade_without_a_mark_has_no_profit_rather_than_a_guess(parts):
    manager, engine = parts
    seed(engine.store)
    out = build_all(manager, engine.store, True, T0, engine.option_lanes)
    flow = next(r for r in out["trades"] if r["source"] == "flow-options")
    assert flow["status"] == "OPEN" and flow["pnl"] is None and flow["mark"] is None
    assert out["summary"]["options"]["open"] == 1


def test_real_and_fictional_ledgers_are_kept_apart(parts):
    manager, engine = parts
    engine.store.lane_open(st_mod.LANE, "SPY", T0, 100.0, 1, False, {})
    out = build_all(manager, engine.store, True, T0, engine.option_lanes)
    assert out["trades"] == []


def test_the_endpoint_needs_the_token_and_returns_the_same_list(parts):
    manager, engine = parts
    seed(engine.store)
    with TestClient(create_app(manager, TOKEN, engine, None)) as c:
        assert c.get("/api/alltrades").status_code == 401
        body = c.get("/api/alltrades", headers=H).json()
    assert body["fictional"] is True and len(body["trades"]) == 4 and body["caveat"]


def test_summaries_carry_the_one_trade_story_check(parts):
    manager, engine = parts
    seed(engine.store)
    out = build_all(manager, engine.store, True, T0 + timedelta(days=3), engine.option_lanes)
    c = out["summary"]["all"]["concentration"]
    assert c["closed"] == out["summary"]["all"]["closed"] == 2 and c["too_thin"] is True
    assert c["best_pnl"] == 198.7 and c["realized_ex_best"] == -50.0
    assert all("concentration" in s for s in out["sources"])


def test_summaries_split_realized_pnl_by_whether_the_size_was_realistic(parts):
    manager, engine = parts
    store = engine.store
    big = store.lane_open("swing-options-base", "SPY", T0, 2.0, 50, True, opt_payload(size_vs_volume_pct=40.0))
    store.lane_close(big, T0 + timedelta(hours=5), 4.0, "target", {"fees_close": 0.65})
    small = store.lane_open("swing-options-base", "QQQ", T0, 2.0, 1, True, opt_payload(size_vs_volume_pct=1.0, size_vs_oi_pct=0.5))
    store.lane_close(small, T0 + timedelta(hours=5), 1.0, "stop", {"fees_close": 0.65})
    out = build_all(manager, store, True, T0 + timedelta(days=3), engine.option_lanes)
    liq = out["summary"]["all"]["liquidity"]
    assert liq["oversized_trades"] == 1 and liq["within_limits_trades"] == 1 and liq["positive_only_if_oversized"] is True
    assert all("liquidity" in s for s in out["sources"])


def test_summaries_split_realized_pnl_by_underlying_and_close_day(parts):
    manager, engine = parts
    seed(engine.store)
    out = build_all(manager, engine.store, True, T0 + timedelta(days=3), engine.option_lanes)
    s = out["summary"]["all"]
    u, d = s["by_underlying"], s["by_day"]
    assert u["closed"] == d["closed"] == s["closed"] == 2
    assert round(sum(r["pnl"] for r in u["groups"]), 2) == round(sum(r["pnl"] for r in d["groups"]), 2) == s["realized_pnl"]
    assert u["too_thin"] is True and d["too_thin"] is True  # fewer than 3 groups
    assert all("by_underlying" in x and "by_day" in x for x in out["sources"])
    assert all(x["closed_drawdown"]["is_account_drawdown"] is False for x in out["sources"])
    assert out["summary"]["all"]["closed_drawdown"]["basis"] == "closed_trades_only"
