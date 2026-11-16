from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from helpers import NOW
from optplat.journal import MIN_SAMPLE, OK, PENDING, UNOBSERVABLE, forward_return, journal_summary
from optplat.marketdata import ChainRow, snapshot_to_dict
from optplat.models import OptionContract, Right
from test_engine import EXPIRY, build, snapshot

ENTRIES = {"auto_entries": True, "reentry_cooldown_s": 0}


def two_row_snapshot(symbol="AAA"):
    base = snapshot(symbol)
    other = ChainRow(OptionContract(symbol, EXPIRY, Right.CALL, 165.0), 4.80, 5.00, 150, 1500, 0.3)
    return replace(base, rows=base.rows + (other,))


# ------------------------------------------------------------ what gets journaled
def test_a_placed_entry_is_journaled_with_rationale_provenance_and_assumptions():
    engine, manager, *_ = build(auto_entries=True)
    engine.run_cycle()
    d = manager.store.list_decisions(kind="ENTRY")[0]
    assert d["disposition"] == "FILLED" and d["order_id"] and d["strategy"].startswith("liquid-trend:")
    assert d["ref_price"] > 5.0  # the limit price: above the 5.10 ask, within the 1% cap
    p = d["payload"]
    assert p["rationale"] and p["quantity"] >= 1 and p["contract"]["underlying"] == "AAA"
    assert p["provenance"]["data_source"] == "static-test" and p["provenance"]["broker"]
    assert any("no demonstrated edge" in a for a in p["assumptions"])
    assert d["fictional"] is False


def test_unverified_quotes_are_stated_as_an_assumption():
    engine, manager, _, provider, _ = build(auto_entries=True)
    provider.set_snapshot(replace(snapshot(), timestamp_verified=False))
    manager.policy = replace(manager.policy, require_verified_quote_time=False)
    engine.run_cycle()
    p = manager.store.list_decisions(kind="ENTRY")[0]["payload"]
    assert any("unverified" in a.lower() for a in p["assumptions"])


def test_a_risk_rejected_candidate_is_journaled_with_the_reasons():
    engine, manager, broker, *_ = build(auto_entries=True)
    manager.policy = replace(manager.policy, max_spread_pct_of_ask=1.0)  # tighter than the 4% spread offered
    report = engine.run_cycle()
    assert report["entries"][0]["result"] == "RISK_REJECTED"
    d = manager.store.list_decisions(kind="ENTRY")[0]
    assert d["disposition"] == "RISK_REJECTED"
    assert any("Spread" in f for f in d["payload"]["risk_failures"])


def test_candidates_that_were_not_chosen_are_journaled_too():
    engine, manager, _, provider, _ = build(auto_entries=True)
    provider.set_snapshot(two_row_snapshot())
    engine.run_cycle()
    dispositions = sorted(d["disposition"] for d in manager.store.list_decisions(kind="ENTRY"))
    assert "FILLED" in dispositions and "NOT_CHOSEN" in dispositions


def test_held_and_cooling_candidates_are_journaled_as_skipped():
    engine, manager, _, provider, clock = build(auto_entries=True)
    engine.run_cycle()  # buys the contract
    clock.now = NOW + timedelta(seconds=2000)
    engine.run_cycle()
    assert "SKIPPED_HELD" in {d["disposition"] for d in manager.store.list_decisions(kind="ENTRY")}


def test_repeated_identical_candidates_are_not_journaled_every_cycle_but_come_back_after_an_hour():
    engine, manager, *_ = build()
    engine.run_cycle()  # sets the cycle time
    c = OptionContract("AAA", EXPIRY, Right.CALL, 165.0)
    count = lambda: len([d for d in manager.store.list_decisions() if d["disposition"] == "NOT_CHOSEN"])  # noqa: E731
    for _ in range(5):
        engine._journal("ENTRY", "AAA", "NOT_CHOSEN", c, 5.0, {})
    assert count() == 1
    engine._cycle_now = engine._cycle_now + timedelta(seconds=3599)
    engine._journal("ENTRY", "AAA", "NOT_CHOSEN", c, 5.0, {})
    assert count() == 1
    engine._cycle_now = engine._cycle_now + timedelta(seconds=2)
    engine._journal("ENTRY", "AAA", "NOT_CHOSEN", c, 5.0, {})
    assert count() == 2
    for _ in range(3):  # orders that reach the broker are always recorded, never deduplicated
        engine._journal("ENTRY", "AAA", "FILLED", c, 5.0, {})
    assert len([d for d in manager.store.list_decisions() if d["disposition"] == "FILLED"]) == 3


def test_exits_are_journaled_but_quiet_holds_are_not():
    engine, manager, _, provider, clock = build(auto_entries=True)
    engine.run_cycle()
    clock.now = NOW + timedelta(seconds=2000)
    engine.run_cycle()  # position held, nothing happens
    assert manager.store.list_decisions(kind="EXIT") == []
    clock.now = NOW + timedelta(seconds=4000)
    provider.set_snapshot(snapshot(bid=7.5, ask=7.7))
    engine.run_cycle()
    ex = manager.store.list_decisions(kind="EXIT")
    assert len(ex) == 1 and ex[0]["disposition"] == "FILLED"
    assert ex[0]["payload"]["trigger"] == "take_profit" and ex[0]["payload"]["pnl_pct"] > 0


def test_a_journal_failure_never_stops_the_cycle(monkeypatch):
    engine, manager, broker, *_ = build(auto_entries=True)

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(manager.store, "record_decision", boom)
    report = engine.run_cycle()
    assert report["entries"][0]["result"] == "FILLED" and len(broker.get_positions()) == 1


def test_journal_records_are_append_only_and_fictional_is_flagged():
    engine, manager, _, provider, _ = build(auto_entries=True)
    provider.fictional = True
    engine.run_cycle()
    assert manager.store.list_decisions()[0]["fictional"] is True
    assert manager.store.list_decisions(include_fictional=False) == []
    assert not hasattr(manager.store, "update_decision")


# ------------------------------------------------------------ forward outcomes
def decision(ref=5.0, ts=NOW, fictional=False):
    c = OptionContract("AAA", EXPIRY, Right.CALL, 160.0)
    return {"ts": ts.isoformat(), "symbol": "AAA", "ref_price": ref, "fictional": fictional,
            "payload": {"contract": c.to_dict()}}


def record_later(store, hours, bid, ask=None, strike=160.0, fictional=False):
    at = NOW + timedelta(hours=hours)
    snap = replace(snapshot(), as_of=at,
                   rows=(ChainRow(OptionContract("AAA", EXPIRY, Right.CALL, strike), bid, ask or bid + 0.2, 100, 1000, 0.3),))
    store.record_snapshot("AAA", at, at, "test", fictional, True, snapshot_to_dict(snap))


def test_forward_return_uses_the_bid_from_the_first_snapshot_at_or_after_the_horizon():
    engine, manager, *_ = build()
    store = manager.store
    record_later(store, 4.1, bid=6.0)
    assert forward_return(store, decision(), 4, NOW + timedelta(hours=5)) == (OK, 20.0)
    assert forward_return(store, decision(), 24, NOW + timedelta(hours=5)) == (PENDING, None)  # too early to know


def test_a_gap_or_missing_contract_is_unobservable_never_estimated():
    engine, manager, *_ = build()
    store = manager.store
    record_later(store, 31.0, bid=6.0)  # the only later snapshot is 7 hours past the 24h mark: a gap
    assert forward_return(store, decision(), 24, NOW + timedelta(hours=40)) == (UNOBSERVABLE, None)
    record_later(store, 29.0, bid=6.0)  # 5 hours past the mark is within the 25% tolerance
    assert forward_return(store, decision(), 24, NOW + timedelta(hours=40)) == (OK, 20.0)
    store.prune_snapshots(NOW + timedelta(hours=29.5))  # forget the 29h reading, leaving only the gappy one
    assert forward_return(store, decision(), 24, NOW + timedelta(hours=40)) == (UNOBSERVABLE, None)
    record_later(store, 4.1, bid=6.0, strike=170.0)  # a snapshot exists but without our contract
    assert forward_return(store, decision(), 4, NOW + timedelta(hours=5)) == (UNOBSERVABLE, None)
    assert forward_return(store, decision(ref=0), 4, NOW + timedelta(hours=5)) == (UNOBSERVABLE, None)


def test_a_later_snapshot_that_fails_the_quality_gate_is_not_used():
    engine, manager, *_ = build()
    store = manager.store
    record_later(store, 4.1, bid=7.0, ask=6.0)  # crossed row: dropped by the gate, so no usable row remains
    assert forward_return(store, decision(), 4, NOW + timedelta(hours=5)) == (UNOBSERVABLE, None)


def test_a_zero_bid_later_is_a_total_loss_not_a_skipped_sample():
    engine, manager, *_ = build()
    record_later(manager.store, 4.1, bid=0.0, ask=0.1)
    assert forward_return(manager.store, decision(), 4, NOW + timedelta(hours=5)) == (OK, -100.0)


def test_real_decisions_never_read_fictional_snapshots():
    engine, manager, *_ = build()
    record_later(manager.store, 4.1, bid=6.0, fictional=True)
    assert forward_return(manager.store, decision(), 4, NOW + timedelta(hours=5)) == (PENDING, None)


# ------------------------------------------------------------ summary
def test_summary_groups_by_disposition_and_marks_small_samples_descriptive():
    engine, manager, _, provider, clock = build(auto_entries=True)
    provider.set_snapshot(two_row_snapshot())
    engine.run_cycle()
    record_later(manager.store, 4.2, bid=6.0)
    summary = journal_summary(manager.store, NOW + timedelta(hours=6))
    assert summary["decisions"] >= 2 and "ENTRY:FILLED" in summary["by_disposition"]
    filled = summary["forward_return_by_disposition"]["FILLED"]
    assert filled["candidates"] == 1 and filled["4h"]["descriptive_only"] is True
    assert filled["24h"]["pending"] == 1 and "not independent" in summary["caveat"]
    assert MIN_SAMPLE == 30


def test_summary_excludes_fictional_decisions_by_default():
    engine, manager, _, provider, _ = build(auto_entries=True)
    provider.fictional = True
    engine.run_cycle()
    assert journal_summary(manager.store, NOW)["decisions"] == 0
    assert journal_summary(manager.store, NOW, include_fictional=True)["decisions"] >= 1


# ------------------------------------------------------------ API
def test_journal_endpoints_need_the_token_and_return_records():
    from test_api_engine import H, TOKEN  # noqa: F401
    from optplat.api import create_app
    from optplat.broker import SimBroker
    from optplat.engine import TradingEngine
    from optplat.marketdata import DemoDataProvider
    from optplat.orders import OrderManager
    from optplat.store import Store
    from optplat.strategy import LiquidTrendStrategy

    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy())
    engine.set_config({"auto_entries": True, "enforce_market_hours": False})
    with TestClient(create_app(manager, TOKEN, engine)) as c:
        assert c.get("/api/journal").status_code == 401 and c.get("/api/journal/summary").status_code == 401
        c.post("/api/engine/cycle", headers=H)
        rows = c.get("/api/journal?limit=5", headers=H).json()
        assert isinstance(rows, list) and len(rows) <= 5
        assert all(r["fictional"] is True for r in rows)  # the demo market is fictional and labelled so
        assert "by_disposition" in c.get("/api/journal/summary", headers=H).json()
