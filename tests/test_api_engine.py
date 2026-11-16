from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, Runner, TradingEngine
from optplat.marketdata import DemoDataProvider
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy

TOKEN = "t" * 24
H = {"X-API-Token": TOKEN}


@pytest.fixture
def client():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    runner = Runner(engine)
    app = create_app(manager, TOKEN, engine, runner)
    with TestClient(app) as c:
        yield c
    runner.stop()


def test_dashboard_is_served_with_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and "options-platform" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    js = client.get("/static/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]


def test_dashboard_never_assigns_html_from_api_data(client):
    src = client.get("/static/app.js").text
    assert "innerHTML" not in src and "outerHTML" not in src and "insertAdjacentHTML" not in src


def test_unexpected_host_header_is_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_engine_endpoints_require_the_token(client):
    for method, path in [("get", "/api/engine/status"), ("post", "/api/engine/cycle"),
                         ("put", "/api/engine/config"), ("get", "/api/report"),
                         ("post", "/api/engine/start"), ("post", "/api/engine/stop")]:
        assert getattr(client, method)(path).status_code == 401, path


def test_status_and_config_round_trip(client):
    status = client.get("/api/engine/status", headers=H).json()
    assert status["config"]["auto_entries"] is False
    assert status["data_source"] == {"name": "demo-synthetic", "fictional": True}
    r = client.put("/api/engine/config", json={"watchlist": ["spy", "qqq"], "auto_entries": True}, headers=H)
    assert r.status_code == 200 and r.json()["watchlist"] == ["SPY", "QQQ"] and r.json()["auto_entries"] is True


def test_invalid_config_is_422(client):
    r = client.put("/api/engine/config", json={"auto_entries": True, "auto_exits": False}, headers=H)
    assert r.status_code == 422 and "auto_exits" in r.json()["detail"]
    assert client.put("/api/engine/config", json={"watchlist": ["bad ticker!"]}, headers=H).status_code == 422


def test_run_cycle_and_loop_controls(client):
    client.put("/api/engine/config", json={"enforce_market_hours": False, "auto_entries": True}, headers=H)
    report = client.post("/api/engine/cycle", headers=H).json()
    assert {"exits", "entries", "errors", "market_open"} <= set(report)
    assert any(e.get("result") == "FILLED" for e in report["entries"])  # demo market is tradable
    assert client.post("/api/engine/start", headers=H).json()["running"] is True
    assert client.post("/api/engine/stop", headers=H).json()["running"] is False
    assert client.get("/api/portfolio", headers=H).json()["positions"]


def test_buy_then_sell_through_the_api_updates_the_report(client):
    expiry = (date.today() + timedelta(days=40)).isoformat()
    contract = {"underlying": "SPY", "expiry": expiry, "right": "C", "strike": 600}
    assert client.post("/api/sim/quote", json={**contract, "bid": 1.90, "ask": 2.00}, headers=H).status_code == 200
    buy = client.post("/api/paper/orders", headers=H, json={
        **contract, "idempotency_key": "api-buy-0001", "candidate_id": "t", "quantity": 4, "limit_price": 2.02}).json()
    assert buy["state"] == "FILLED"
    sell = client.post("/api/paper/orders", headers=H, json={
        **contract, "idempotency_key": "api-sell-0001", "candidate_id": "t", "quantity": 4,
        "limit_price": 1.85, "side": "SELL_TO_CLOSE"}).json()
    assert sell["state"] == "FILLED" and sell["cost_basis"] == 2.01
    report = client.get("/api/report", headers=H).json()
    assert report["closed_trades"] == 1 and report["open"] == []


def test_selling_without_a_position_is_rejected_not_errored(client):
    expiry = (date.today() + timedelta(days=40)).isoformat()
    contract = {"underlying": "SPY", "expiry": expiry, "right": "C", "strike": 600}
    client.post("/api/sim/quote", json={**contract, "bid": 1.90, "ask": 2.00}, headers=H)
    r = client.post("/api/paper/orders", headers=H, json={
        **contract, "idempotency_key": "api-sell-0002", "candidate_id": "t", "quantity": 1,
        "limit_price": 1.85, "side": "SELL_TO_CLOSE"})
    assert r.status_code == 200 and r.json()["state"] == "RISK_REJECTED"


def test_dashboard_has_results_panel_that_uses_the_results_api():
    """UX: results (sample gate, split-half, unrealized) are visible on first sight, text only."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src" / "optplat" / "static"
    html, js = (root / "index.html").read_text(), (root / "app.js").read_text()
    assert 'id="results-status"' in html and "not proof of an edge" in html
    assert '"/api/results"' in js and "renderResults" in js
    assert "How fills are simulated" in js and "NOT modeled" in js
    assert "innerHTML" not in js


def test_glance_summary_is_text_only_and_flags_unsafe_states():
    """Runs the dashboard's buildGlance under node with a stub DOM (skips if node is missing)."""
    import json, shutil, subprocess
    from pathlib import Path
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not installed")
    root = Path(__file__).resolve().parents[1] / "src" / "optplat" / "static"
    js = (root / "app.js").read_text()
    assert "innerHTML" not in js and 'id="glance"' in (root / "index.html").read_text()
    harness = """
global.document={getElementById:()=>({addEventListener(){}}),createElement:()=>({})};
global.window={};global.sessionStorage={getItem:()=>''};global.fetch=()=>{};global.setInterval=()=>0;
require(process.argv[1]);
const g=window.optplatGlance;
const st={data_source:{name:'x',fictional:true},config:{auto_entries:true,auto_exits:false},last_cycle:{errors:['boom'],entries:[],exits:[]},runner:{running:false}};
const bad=g({mode:'LIVE'},st,{kill_switch:true},{status:'INSUFFICIENT_SAMPLE',closed_trades:2,open_positions:{unrealized_pnl_usd:null}},{max_position_pct:1,max_total_premium_pct:10,max_open_positions:12});
const none=g({mode:'PAPER'},{config:{}},null,null,null);
const now=Date.parse('2026-11-16T12:00:00Z');
const st2={data_source:{name:'x',fictional:false},market:{open:false,reason:'Weekend'},config:{auto_entries:false,auto_exits:true,enforce_market_hours:false,interval_s:300},runner:{running:true},last_cycle:{errors:[],entries:[],exits:[],started_at:'2026-11-16T11:00:00Z'}};
const stale=g({mode:'PAPER'},st2,{kill_switch:false},null,null,now);
const fresh=g({mode:'PAPER'},{...st2,market:{open:true,reason:'Regular session'},config:{...st2.config,enforce_market_hours:true},last_cycle:{...st2.last_cycle,started_at:'2026-11-16T11:58:00Z'}},{kill_switch:false},null,null,now);
const srvStalled=g({mode:'PAPER'},{...st2,runner:{running:true,stalled:true,seconds_since_success:1200,consecutive_failures:0}},{kill_switch:false},null,null,now);
const srvFail=g({mode:'PAPER'},{...st2,runner:{running:true,stalled:false,consecutive_failures:3,last_error:'RuntimeError: x'}},{kill_switch:false},null,null,now);
const srvOk=g({mode:'PAPER'},{...st2,last_cycle:{...st2.last_cycle,started_at:'2026-11-16T10:00:00Z'},runner:{running:true,stalled:false,consecutive_failures:0}},{kill_switch:false},null,null,now);
console.log(JSON.stringify({bad,none,stale,fresh,srvStalled,srvFail,srvOk}));
"""
    out = subprocess.run([node, "-e", harness, str(root / "app.js")], capture_output=True, text=True, check=True).stdout
    r = json.loads(out)
    text = " ".join(i["text"] for i in r["bad"])
    assert any(i["level"] == "bad" and "not PAPER" in i["text"] for i in r["bad"])
    assert "Kill switch is ON" in text and "FICTIONAL" in text and "boom" in text and "loop is stopped" in text
    assert "too few to judge" in text and "cannot be fully measured" in text
    # missing data must never read as fine
    assert any("unknown" in i["text"] and i["level"] == "warn" for i in r["none"])
    assert not any("Kill switch is off" in i["text"] for i in r["none"])

    # market session, hours-check and stale-loop lines
    stale = " ".join(i["text"] for i in r["stale"])
    assert "Market is closed (Weekend)" in stale and "Market-hours check is OFF" in stale and "may be stalled" in stale
    assert any(i["level"] == "warn" and "may be stalled" in i["text"] for i in r["stale"])
    fresh = " ".join(i["text"] for i in r["fresh"])
    assert "Market is open" in fresh and "stalled" not in fresh and "check is OFF" not in fresh
    assert any("Market session unknown" in i["text"] and i["level"] == "warn" for i in r["none"])

    # server-reported runner health wins over the client-side age guess
    assert any("reports the loop as stalled" in i["text"] and i["level"] == "warn" for i in r["srvStalled"])
    assert any("failed 3 cycle(s) in a row" in i["text"] and i["level"] == "bad" for i in r["srvFail"])
    assert not any("stalled" in i["text"] for i in r["srvOk"])
