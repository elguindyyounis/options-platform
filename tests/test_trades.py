from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, TradingEngine
from optplat.events import EventCalendar
from optplat.marketdata import DemoDataProvider
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy
from test_committee import calm
from test_engine import build

TOKEN = "t" * 24
H = {"X-API-Token": TOKEN}
EXPIRY = (date.today() + timedelta(days=40)).isoformat()
CONTRACT = {"underlying": "SPY", "expiry": EXPIRY, "right": "C", "strike": 600}


@pytest.fixture
def client():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    with TestClient(create_app(manager, TOKEN, engine)) as c:
        yield c


def quote(c, bid=1.90, ask=2.00):
    assert c.post("/api/sim/quote", json={**CONTRACT, "bid": bid, "ask": ask}, headers=H).status_code == 200


def order(c, key, qty, side="BUY_TO_OPEN", limit=2.02):
    r = c.post("/api/paper/orders", headers=H, json={**CONTRACT, "idempotency_key": key, "candidate_id": "t",
                                                      "quantity": qty, "limit_price": limit, "side": side})
    assert r.status_code == 200
    return r.json()


def trades(c):
    return c.get("/api/trades", headers=H).json()


def test_requires_the_token_and_starts_empty(client):
    assert client.get("/api/trades").status_code == 401 and client.get("/api/trades/x").status_code == 401
    body = trades(client)
    assert body["trades"] == [] and body["summary"]["total"] == 0 and body["summary"]["win_rate_pct"] is None


def test_an_open_trade_is_marked_at_the_bid(client):
    quote(client)
    buy = order(client, "buy-0001-aa", 4)
    t = trades(client)["trades"][0]
    assert t["status"] == "OPEN" and t["id"] == buy["id"] and t["remaining"] == 4 and t["exit_price"] is None
    assert t["mark"] == 1.90 and t["unrealized_pnl"] == round((1.90 - t["entry_price"]) * 4 * 100, 2)
    assert t["pnl"] == t["unrealized_pnl"] and t["pnl_pct"] < 0  # paying the ask and marking at the bid starts negative


def test_a_closed_trade_reports_realized_pnl_exit_and_holding_time(client):
    quote(client)
    order(client, "buy-0002-aa", 4)
    quote(client, 2.60, 2.70)
    order(client, "sell-0002-aa", 4, "SELL_TO_CLOSE", 2.55)
    body = trades(client)
    t = body["trades"][0]
    assert t["status"] == "CLOSED" and t["remaining"] == 0 and t["mark"] is None
    assert t["pnl"] == round((t["exit_price"] - t["entry_price"]) * 4 * 100, 2) > 0
    assert t["held_seconds"] is not None and t["held_seconds"] >= 0
    s = body["summary"]
    assert s["closed"] == 1 and s["wins"] == 1 and s["win_rate_pct"] == 100.0 and s["open"] == 0 and s["realized_pnl"] == t["pnl"]


def test_a_partial_exit_leaves_the_rest_open_and_marked(client):
    quote(client)
    order(client, "buy-0003-aa", 2)
    order(client, "sell-0003-aa", 1, "SELL_TO_CLOSE", 1.85)
    t = trades(client)["trades"][0]
    assert t["status"] == "PARTIAL" and t["exited_qty"] == 1 and t["remaining"] == 1
    assert t["realized_pnl"] != 0 and t["unrealized_pnl"] is not None and t["exit_price"] is not None


def test_a_re_entry_is_a_separate_trade_and_exits_match_the_right_one(client):
    quote(client)
    order(client, "buy-0003-bb", 1)
    order(client, "sell-0003-bb", 1, "SELL_TO_CLOSE", 1.85)
    order(client, "buy-0003-cc", 1)  # the risk gate allows no duplicate open contract, so a re-entry follows the exit
    older, newer = sorted(trades(client)["trades"], key=lambda t: t["entry_time"])
    assert older["status"] == "CLOSED" and newer["status"] == "OPEN" and newer["exited_qty"] == 0


def test_a_position_that_cannot_be_priced_is_unobservable_not_zero(client):
    quote(client)
    order(client, "buy-0004-aa", 2)
    quote(client, 0.0, 2.00)  # no bid: the mark is unobservable
    body = trades(client)
    t = body["trades"][0]
    assert t["mark"] is None and t["unrealized_pnl"] is None and t["pnl"] is None and t["pnl_pct"] is None
    assert body["summary"]["unobservable_open"] == 1


def test_trade_detail_has_the_audit_trail_and_unknown_ids_404(client):
    quote(client)
    buy = order(client, "buy-0005-aa", 1)
    d = client.get(f"/api/trades/{buy['id']}", headers=H).json()
    assert d["id"] == buy["id"] and d["audit"] and all("ts" in e for e in d["audit"])
    assert client.get("/api/trades/nope", headers=H).status_code == 404


def test_a_committee_entry_carries_its_reasoning_and_every_agents_vote():
    engine, manager, _, provider, _ = build(auto_entries=True, committee_mode="active")
    provider.set_snapshot(calm())
    engine.calendar = EventCalendar(earnings_source=lambda s: [])
    engine.run_cycle()
    from optplat.trades import build_trades

    out = build_trades(manager)
    assert len(out["trades"]) == 1
    t = out["trades"][0]
    assert t["entry_reason"] and t["entry_reason"]["strategy"].startswith("liquid-trend")
    assert t["committee"] and {v["agent"] for v in t["committee"]["verdicts"]} >= {"technical", "skeptic", "events", "execution"}
    assert 1 <= t["committee"]["quantity"] <= 10 and t["committee"]["reasons"]


def test_an_exit_trade_names_its_trigger():
    engine, manager, broker, provider, clock = build(auto_entries=True, committee_mode="off")
    engine.run_cycle()
    from test_engine import snapshot

    provider.set_snapshot(snapshot(bid=7.5, ask=7.7))  # far above the take-profit level
    engine.run_cycle()
    from optplat.trades import build_trades

    t = build_trades(manager)["trades"][0]
    assert t["status"] == "CLOSED" and t["exit_reason"] and "take" in str(t["exit_reason"]).lower()


def test_an_exit_with_the_same_timestamp_as_its_entry_is_still_matched():
    """Regression: ties were once broken by a random id, so the exit could be processed before its entry."""
    for _ in range(25):
        engine, manager, broker, provider, clock = build(auto_entries=True, committee_mode="off")
        engine.run_cycle()
        from test_engine import snapshot

        provider.set_snapshot(snapshot(bid=7.5, ask=7.7))
        engine.run_cycle()
        from optplat.trades import build_trades

        assert build_trades(manager)["trades"][0]["status"] == "CLOSED"
