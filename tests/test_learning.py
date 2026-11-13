from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from optplat import learning
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, TradingEngine
from optplat.marketdata import DemoDataProvider
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy


def trade(i, pct):
    return {"status": "CLOSED", "pnl": pct, "pnl_pct": pct, "closed_at": (datetime(2026, 11, 1, tzinfo=timezone.utc) + timedelta(minutes=i)).isoformat()}


def test_too_few_closed_trades_gets_no_verdict():
    out = learning.improvement([trade(i, 5.0) for i in range(30)])
    assert out["verdict"] == "TOO_EARLY" and "30 trades" in out["text"] and out["older"] is None
    assert learning.improvement([])["verdict"] == "TOO_EARLY"


def test_open_trades_and_trades_without_a_result_are_not_counted():
    rows = [trade(i, 5.0) for i in range(10)] + [{"status": "OPEN", "pnl": None, "pnl_pct": None, "closed_at": None}, {"status": "CLOSED", "pnl": None, "pnl_pct": None, "closed_at": "x"}]
    assert learning.improvement(rows)["closed_trades"] == 10


def test_a_clearly_better_newer_half_is_called_improving_and_a_clearly_worse_one_worsening():
    better = [trade(i, -10.0) for i in range(30)] + [trade(i + 30, 12.0) for i in range(30)]
    out = learning.improvement(better)
    assert out["verdict"] == "IMPROVING" and out["older"]["n"] == 30 and out["change_return_pts"] == 22.0 and "better" in out["text"]
    assert learning.improvement(list(reversed(better)))["verdict"] == "IMPROVING"  # the order the rows arrive in never matters
    worse = [trade(i, 12.0) for i in range(30)] + [trade(i + 30, -10.0) for i in range(30)]
    assert learning.improvement(worse)["verdict"] == "WORSENING"


def test_a_small_gap_is_no_clear_change():
    rows = [trade(i, 3.0 if i % 2 else -3.0) for i in range(60)]
    assert learning.improvement(rows)["verdict"] == "NO_CLEAR_CHANGE"


def test_the_report_labels_how_strong_each_lesson_is():
    digest = {"tags": [{"tag": "A", "count": 12, "avg_net_pct": -20.0, "means": "Wide spreads ate it.", "try_next": "Skip wide spreads.", "pattern": True},
                       {"tag": "B", "count": 2, "avg_net_pct": -5.0, "means": "Early stop.", "try_next": "Wait.", "pattern": False}]}
    out = learning.build([trade(1, 1.0)], [{"ts": "2026-11-12T00:00:00+00:00", "agent": "flow", "note": "0.25 to 0.30"}], {"lessons": ["Entered and lost: X"], "agents": {}, "committee": {}},
                         digest, {"findings": ["Call or put: ..."], "total_marks": 50}, {"history": [{"ended_at": "2026-11-12T01:00:00+00:00", "attempt": 1, "outcome": "RUIN", "multiple": 0.3}], "attempts_finished": 1, "honesty": "0 of 1."},
                         [{"id": "H-0001", "statement": "S", "status": "NOT_EVALUATED"}], True, "2026-11-13T00:00:00+00:00")
    strengths = {l["strength"] for l in out["lessons"]}
    assert "Pattern" in strengths and "Anecdote (too few trades)" in strengths and any(s.startswith("Lead to test") for s in strengths)
    kinds = [e["kind"] for e in out["timeline"]]
    assert {"trades", "agent", "challenge"} <= set(kinds) and out["timeline"] == sorted(out["timeline"], key=lambda e: e["ts"], reverse=True)
    assert out["counts"]["tracker_marks"] == 50 and out["caveat"]


def test_the_endpoint_works_on_an_empty_platform_and_needs_the_token():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    with TestClient(create_app(manager, "t" * 24, engine, None)) as c:
        assert c.get("/api/learning").status_code == 401
        body = c.get("/api/learning", headers={"X-API-Token": "t" * 24}).json()
    assert body["improvement"]["verdict"] == "TOO_EARLY" and body["timeline"] == [] and body["summary"]
