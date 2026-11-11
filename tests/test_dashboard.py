import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from helpers import NOW
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, Runner, TradingEngine
from optplat.evaluation import equity_summary
from optplat.marketdata import DemoDataProvider
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy
from test_engine import SATURDAY, build

TOKEN = "t" * 24
H = {"X-API-Token": TOKEN}


@pytest.fixture
def client():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    runner = Runner(engine)
    with TestClient(create_app(manager, TOKEN, engine, runner)) as c:
        yield c, engine
    runner.stop()


# ------------------------------------------------------------ panels answer a question
def test_every_dashboard_section_states_its_question_or_is_marked_plumbing(client):
    html = client[0].get("/").text
    sections = re.findall(r"<section\b[^>]*>", html)
    assert len(sections) >= 7
    for tag in sections:
        assert "data-question=" in tag or "data-plumbing=" in tag, tag
    # the duplicated per-cycle table is gone: the decision journal answers "why" instead
    assert "cycle-table" not in html


def test_dashboard_script_still_never_assigns_html_and_ids_match(client):
    c, _ = client
    js, html = c.get("/static/app.js").text, c.get("/").text
    assert "innerHTML" not in js and "outerHTML" not in js and "insertAdjacentHTML" not in js
    for ident in set(re.findall(r'\$\("([a-z\-]+)"\)', js)):
        assert f'id="{ident}"' in html, f"app.js reads #{ident} which index.html does not define"


def test_chart_has_a_table_view_a_keyboard_path_and_dark_mode_colour(client):
    c, _ = client
    js, html = c.get("/static/app.js").text, c.get("/").text
    assert "Show as table" in html and "ArrowLeft" in js and "createElementNS" in js
    assert "--series-1" in html and html.count("--series-1:") == 2  # light and dark values


# ------------------------------------------------------------ equity
def test_equity_summary_basics():
    s = equity_summary([{"equity": 100.0}, {"equity": 110.0}, {"equity": 99.0}])
    assert s["change_pct"] == -1.0 and s["peak"] == 110.0
    assert s["current_drawdown_pct"] == 10.0 and s["max_drawdown_pct"] == 10.0
    assert equity_summary([])["points"] == 0 and equity_summary([])["last"] is None


def test_equity_endpoint_requires_token_and_returns_points(client):
    c, engine = client
    assert c.get("/api/equity").status_code == 401
    assert c.get("/api/research/hypotheses").status_code == 401
    t0 = NOW
    for i in range(3):
        engine.store.record_equity(t0 + timedelta(minutes=5 * i), 100_000 + i, 99_000, 1_000, True)
    engine.store.record_equity(t0, 5.0, 5.0, 0.0, False)  # a real-data point must not leak into a fictional curve
    body = c.get("/api/equity", headers=H).json()
    assert body["fictional"] is True and [p["equity"] for p in body["points"]] == [100_000, 100_001, 100_002]
    assert set(body["points"][0]) == {"ts", "equity"} and body["summary"]["points"] == 3


def test_hypotheses_endpoint_is_empty_then_lists_registered(client):
    c, _ = client
    assert c.get("/api/research/hypotheses", headers=H).json() == []


def test_engine_records_equity_only_when_trading_is_allowed():
    engine, _, _, _, clock = build(enforce_market_hours=True)
    clock.now = SATURDAY
    engine.run_cycle()
    assert engine.store.list_equity() == []  # market closed: no flat overnight point
    clock.now = NOW  # a regular session time in the shared fixtures
    engine.run_cycle()
    pts = engine.store.list_equity()
    assert len(pts) == 1 and pts[0]["equity"] > 0


def test_equity_prune_removes_only_old_points():
    store = Store(":memory:")
    now = datetime(2026, 11, 11, tzinfo=timezone.utc)
    store.record_equity(now - timedelta(days=200), 1.0, 1.0, 0.0, False)
    store.record_equity(now, 2.0, 2.0, 0.0, False)
    assert store.prune_equity(now - timedelta(days=90)) == 1
    assert [p["equity"] for p in store.list_equity()] == [2.0]


def test_equity_points_come_back_in_time_order_even_if_inserted_out_of_order():
    store = Store(":memory:")
    t = datetime(2026, 11, 11, tzinfo=timezone.utc)
    store.record_equity(t, 3.0, 0, 0, False)
    store.record_equity(t - timedelta(days=2), 1.0, 0, 0, False)
    store.record_equity(t - timedelta(days=1), 2.0, 0, 0, False)
    assert [p["equity"] for p in store.list_equity()] == [1.0, 2.0, 3.0]


# ------------------------------------------------------------ dashboard v2: pages, trades, scan
def test_every_nav_link_has_a_page_with_a_question(client):
    html = client[0].get("/").text
    pages = re.findall(r'<a class="nav" href="#/([a-z]+)" data-page="([a-z]+)"', html)
    assert [p for p, _ in pages] == ["desk", "trades", "market", "agents", "research", "system"]
    for route, page in pages:
        assert route == page
        tag = re.search(rf'<section[^>]*data-page="{page}"[^>]*>', html)
        assert tag and "data-question=" in tag.group(0), page


def test_dashboard_keeps_the_safety_behaviours_in_the_script(client):
    js = client[0].get("/static/app.js").text
    assert "LOOP STALLED" in js and "history.replaceState" in js and "X-API-Token" in js
    assert "/api/trades" in js and "/api/scan" in js and "kind=COMMITTEE" in js
    # the trade file is a real dialog that traps focus and closes on Escape
    html = client[0].get("/").text
    assert 'role="dialog"' in html and 'aria-modal="true"' in html
    assert '"Escape"' in js and "trapFocus" in js
    assert "No live orders exist" in html


def test_journal_can_be_filtered_by_kind_and_rejects_odd_values(client):
    c, engine = client
    for kind in ("COMMITTEE", "ENTRY"):
        engine.store.record_decision(NOW, "SPY", kind, "WOULD_REJECT", "SPY  261218C00600000", "t", 1.0, None, True, {"net_score": 0.1})
    only = c.get("/api/journal?kind=COMMITTEE", headers=H).json()
    assert len(only) == 1 and only[0]["kind"] == "COMMITTEE"
    assert len(c.get("/api/journal", headers=H).json()) == 2  # no filter: unchanged behaviour
    assert c.get("/api/journal?kind=x;drop", headers=H).status_code == 422
    assert c.get("/api/journal?kind=lower", headers=H).status_code == 422
    assert c.get("/api/journal?kind=COMMITTEE").status_code == 401


def test_scan_and_trades_endpoints_are_what_the_dashboard_reads(client):
    c, _ = client
    assert c.get("/api/scan").status_code == 401 and c.get("/api/trades").status_code == 401
    scan = c.get("/api/scan", headers=H).json()
    assert set(scan) >= {"status", "result", "interval_s"}
    trades = c.get("/api/trades", headers=H).json()
    assert set(trades) >= {"summary", "trades", "fictional"} and trades["fictional"] is True
