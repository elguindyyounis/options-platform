import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from optplat import challenge as ch
from optplat import optionlanes as ol
from optplat.postmortem import post_mortem
from optplat.store import Store
from test_optionlanes import OptFeed, short_up

SYMS = replace(ch.CHALLENGE, symbols=("SPY",))


def build(bars, now, params=SYMS):
    box = [now]
    prov = OptFeed(lambda: box[0], bars)
    store = Store(":memory:")
    lane = ch.ChallengeLane.__new__(ch.ChallengeLane)
    ol.OptionLane.__init__(lane, prov, store, params, ol.Feed(prov, lambda: box[0]), clock=lambda: box[0])
    lane._attempt = {}
    return lane, prov, store, box


def trades(lane, store):
    return store.lane_trades(lane.p.lane, True, 100)


def test_the_account_sizes_a_trade_as_a_share_of_its_equity_and_records_the_critic():
    bars, now = short_up()
    lane, prov, store, _ = build(bars, now)
    out = lane.step(force=True)
    t = trades(lane, store)
    assert len(t) == 1, out
    o = t[0]["open_payload"]
    assert o["attempt"] == 1 and o["critic"]["verdict"] in ("ACCEPTED", "ACCEPTED_WITH_OBJECTIONS")
    assert o["critic"]["thesis"] and o["critic"]["wrong_if"] and o["critic"]["needs_pct_per_day_for_goal"] > 0
    cost = t[0]["entry_price"] * t[0]["quantity"] * 100
    assert cost <= ch.START_EQUITY * ch.RISK_PCT + 1 and o["size_vs_volume_pct"] <= ch.MAX_SIZE_OF_VOLUME_PCT + 0.5


def test_the_critic_cuts_size_to_what_the_market_can_absorb():
    bars, now = short_up()
    lane, prov, store, _ = build(bars, now)
    real = prov.snapshot_window
    def thin(symbol, *a, **k):
        snap = real(symbol, *a, **k)
        rows = tuple(replace(r, volume=120, open_interest=300) for r in snap.rows)
        return replace(snap, rows=rows)
    prov.snapshot_window = thin
    lane.step(force=True)
    t = trades(lane, store)
    assert len(t) == 1 and t[0]["quantity"] <= 12  # 10% of 120 contracts of volume
    assert any("size cut" in x for x in t[0]["open_payload"]["critic"]["objections"]) or t[0]["quantity"] <= 12


def test_a_book_that_is_already_too_exposed_is_refused_with_the_reason():
    bars, now = short_up()
    lane, prov, store, _ = build(bars, now)
    lane._load_attempt(now)
    store.lane_open(lane.p.lane, "QQQ", now, 5.0, 12, True, {"multiplier": 100, "fees_open": 7.8, "fee_per_contract": 0.65, "attempt": 1,
                                                          "contract": "QQQ X", "right": "C", "expiry": "2026-12-18", "strike": 1.0})
    out = lane.step(force=True)
    assert len(trades(lane, store)) == 1 and any("critic" in s and "at risk at once" in s for s in out["skips"]), out


def test_three_losses_in_a_row_mean_a_cooling_off_and_a_stopped_out_name_is_not_chased():
    bars, now = short_up()
    lane, prov, store, _ = build(bars, now)
    lane._load_attempt(now)
    for i in range(3):
        tid = store.lane_open(lane.p.lane, "QQQ", now - timedelta(minutes=50), 2.0, 1, True,
                              {"multiplier": 100, "fees_open": 0.65, "fee_per_contract": 0.65, "attempt": 1, "right": "C", "contract": "Q"})
        store.lane_close(tid, now - timedelta(minutes=20), 1.0, "stop", {"fees_close": 0.65})
    out = lane.step(force=True)
    assert trades(lane, store)[0]["symbol"] == "QQQ" and len(trades(lane, store)) == 3
    assert any("cooling off" in s for s in out["skips"]), out


def test_reaching_ten_times_ends_the_attempt_as_a_target_and_a_new_one_starts():
    bars, now = short_up()
    lane, prov, store, _ = build(bars, now)
    lane._load_attempt(now)
    tid = store.lane_open(lane.p.lane, "QQQ", now - timedelta(hours=5), 1.0, 1, True, {"multiplier": 100, "fees_open": 0, "fee_per_contract": 0, "attempt": 1, "right": "C", "contract": "Q"})
    store.lane_close(tid, now - timedelta(hours=1), 1001.0, "target", {"fees_close": 0})  # +$100,000 on paper
    out = lane.step(force=True)
    hist = json.loads(store.get_state("challenge:history", "[]"))
    assert hist[0]["outcome"] == "TARGET" and hist[0]["attempt"] == 1 and hist[0]["multiple"] >= 10
    assert json.loads(store.get_state("challenge:attempt"))["n"] == 2 and "attempt 1 ended" in out.get("note", "")


def test_losing_ninety_percent_ends_the_attempt_as_ruin_and_the_restart_is_counted():
    bars, now = short_up()
    lane, prov, store, _ = build(bars, now)
    lane._load_attempt(now)
    tid = store.lane_open(lane.p.lane, "QQQ", now - timedelta(hours=5), 100.0, 1, True, {"multiplier": 100, "fees_open": 0, "fee_per_contract": 0, "attempt": 1, "right": "C", "contract": "Q"})
    store.lane_close(tid, now - timedelta(hours=1), 0.05, "stop", {"fees_close": 0})  # -$9,995
    lane.step(force=True)
    hist = json.loads(store.get_state("challenge:history"))
    assert hist[0]["outcome"] == "RUIN" and json.loads(store.get_state("challenge:attempt"))["n"] == 2
    rep = lane.report(now)
    assert rep["outcomes"]["RUIN"] == 1 and rep["success_rate_pct"] == 0.0 and "0 of 1 reached 10x" in rep["honesty"]
    assert rep["account"]["attempt"] == 2 and abs(rep["account"]["equity"] - ch.START_EQUITY) < 150  # a fresh $10,000 (less the cost of any trade opened since)


def test_the_deadline_ends_an_attempt_and_a_manual_restart_is_logged_like_any_other_end():
    bars, now = short_up()
    lane, prov, store, box = build(bars, now)
    lane._load_attempt(now)
    box[0] = now + timedelta(days=31)
    lane.step(force=True)
    assert json.loads(store.get_state("challenge:history"))[0]["outcome"] == "DEADLINE"
    res = lane.restart(box[0])
    assert res["restarted"] and [h["outcome"] for h in json.loads(store.get_state("challenge:history"))] == ["DEADLINE", "MANUAL_RESTART"]


def test_an_open_position_with_no_quote_keeps_the_attempt_open_instead_of_guessing():
    bars, now = short_up()
    lane, prov, store, box = build(bars, now)
    lane._load_attempt(now)
    store.lane_open(lane.p.lane, "ZZZZ", now - timedelta(days=1), 1.0, 1, True, {"multiplier": 100, "fees_open": 0, "fee_per_contract": 0.65, "attempt": 1, "right": "C",
                                                                                 "contract": "ZZZZ  991231C00001000", "expiry": "2099-12-31", "strike": 1.0})
    prov.quotes_for = lambda contracts: []   # the feed has no quote for it
    box[0] = now + timedelta(days=31)
    out = lane.step(force=True)
    assert json.loads(store.get_state("challenge:attempt"))["n"] == 1 and store.get_state("challenge:history", "[]") == "[]"
    assert out["errors"]


def test_account_maths_and_the_required_pace():
    t = {"open_payload": {"multiplier": 100, "fees_open": 1.3, "fee_per_contract": 0.65}, "entry_price": 2.0, "quantity": 2, "closed_at": None, "close_payload": None, "id": 1, "exit_price": None}
    st = ch.account_state([t], 10_000, {1: 3.0})
    assert st["cash"] == 10_000 - 401.3 and st["equity"] == round(10_000 - 401.3 + 600 - 1.3, 2) and st["unmarked"] == 0
    assert ch.account_state([t], 10_000, {})["unmarked"] == 1
    assert 10.0 < ch.required_daily_pct(10_000, 100_000, 21) < 12.0   # about 11.6% a day over 21 trading days
    assert ch.required_daily_pct(0, 100_000, 10) is None and ch.required_daily_pct(5_000, 100_000, 0) is None


def test_the_challenge_never_leaves_the_research_ledger():
    import ast, inspect
    tree = ast.parse(inspect.getsource(ch))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {a.attr for a in ast.walk(tree) if isinstance(a, ast.Attribute)}
    assert not names & {"OrderManager", "RiskPolicy", "submit_limit_order", "SimBroker", "submit_buy"}


def test_the_challenge_end_reason_is_understood_by_the_post_mortem():
    t = {"symbol": "A", "entry_price": 2.0, "quantity": 1, "opened_at": datetime(2026, 11, 12, 15, tzinfo=timezone.utc).isoformat(),
         "open_payload": {"right": "C", "multiplier": 100, "fees_open": 0.65, "underlying_price": 100.0, "spread_pct": 3, "open_interest": 900, "dte": 3, "kind": "short", "contract": "A"}}
    pm = post_mortem(t, 1.5, "challenge_end", datetime(2026, 11, 12, 18, tzinfo=timezone.utc), {"underlying": 99.0, "fees_close": 0.65, "spread_pct": 3})
    assert pm["net_pct"] < 0 and "challenge end" in pm["headline"]


def test_the_api_serves_the_challenge_behind_the_token_and_restarts_are_counted():
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
    assert c.get("/api/challenge").status_code == 401
    body = c.get("/api/challenge", headers={"X-API-Token": "t" * 24}).json()
    assert body["account"]["attempt"] == 1 and body["account"]["equity"] == ch.START_EQUITY and body["fictional"] is True
    assert body["honesty"] and body["limitations"] and body["rules"]
    assert c.post("/api/challenge/restart", headers={"X-API-Token": "t" * 24}).json()["restarted"] is True
    assert c.get("/api/challenge", headers={"X-API-Token": "t" * 24}).json()["outcomes"]["MANUAL_RESTART"] == 1
