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


def test_dashboard_reads_a_launcher_token_from_the_fragment_and_scrubs_it(client):
    src = client.get("/static/app.js").text
    assert "location.hash" in src and "history.replaceState" in src


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


def test_status_exposes_recorder_counts_and_config_accepts_retention(client):
    r = client.get("/api/engine/status", headers=H).json()
    assert r["recorder"]["total"] == 0 and r["config"]["record_snapshots"] is True
    ok = client.put("/api/engine/config", json={"snapshot_retention_days": 7}, headers=H)
    assert ok.status_code == 200 and ok.json()["snapshot_retention_days"] == 7
    bad = client.put("/api/engine/config", json={"snapshot_retention_days": 0}, headers=H)
    assert bad.status_code == 422 or bad.status_code == 400


def test_health_shows_runner_flags_but_never_error_text_and_status_shows_the_detail(client):
    body = client.get("/api/health").json()
    assert set(body["runner"]) == {"running", "stalled", "seconds_since_success"}
    detail = client.get("/api/engine/status", headers=H).json()["runner"]
    assert {"last_error", "last_success_at", "stalled"} <= set(detail)


def test_dashboard_warns_when_the_loop_is_stalled(client):
    src = client.get("/static/app.js").text
    assert "LOOP STALLED" in src and "rn.stalled" in src
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
const stub=()=>new Proxy(function(){},{get:(t,k)=>k==='matches'?false:(k==='style'||k==='classList'||k==='dataset')?stub():stub(),set:()=>true,apply:()=>stub()});
global.document={getElementById:()=>stub(),createElement:()=>stub(),querySelectorAll:()=>[],addEventListener(){},createTextNode:()=>stub()};
global.window={matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener(){}};global.location={hash:''};global.history={replaceState(){}};
global.sessionStorage={getItem:()=>'',setItem(){},removeItem(){}};global.fetch=()=>new Promise(()=>{});global.setInterval=()=>0;global.setTimeout=()=>0;
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
const mk=(a)=>g({mode:'PAPER'},{config:{}},{kill_switch:false,account:a},null,null,now);
const riskLow=mk({equity:1000,open_premium:100});const riskHigh=mk({equity:1000,open_premium:600});const riskMissing=mk({equity:0});
const strat=g({mode:'PAPER'},{config:{},strategy:{name:'flow-otm',version:'1.0'}},{kill_switch:false},null,null,now);
const cal=g({mode:'PAPER'},{config:{},market:{open:false,reason:'x',upcoming:[{date:'2026-11-26',kind:'closed'},{date:'2026-11-27',kind:'early_close'}]}},{kill_switch:false},null,null,now);
const ordered=window.optplatGlanceOrder(bad).map(i=>i.level);const stable=window.optplatGlanceOrder([{level:'ok',text:'a'},{level:'warn',text:'b'},{level:'ok',text:'c'},{level:'bad',text:'d'},{level:'warn',text:'e'}]).map(i=>i.text);
const halt=g({mode:'PAPER'},{config:{auto_entries:true,auto_exits:true}},{kill_switch:false},null,null,now);
const helped=g({mode:'PAPER'},{config:{},last_cycle:{errors:['data NVDA: rejected (EMPTY_CHAIN: x)'],entries:[],exits:[],error_help:[{error:'data NVDA: rejected (EMPTY_CHAIN: x)',cause:'No source gave a usable option quote for NVDA.',fix:'Nothing if it clears.',who:'wait',repeats:1,alert:false},{error:'data SPY: rejected (FUTURE_TIMESTAMP: y)',cause:'Clock behind.',fix:'Set time automatically.',who:'you',repeats:4,alert:true}]}},{kill_switch:false},null,null,now);
console.log(JSON.stringify({helped,halt,ordered,stable,cal,strat,riskLow,riskHigh,riskMissing,bad,none,stale,fresh,srvStalled,srvFail,srvOk}));
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

    # most urgent first, stable inside a level (UX run 24); original list is not mutated
    rank = {"bad": 0, "warn": 1, "ok": 2}
    assert r["ordered"] == sorted(r["ordered"], key=rank.get) and r["ordered"][0] == "bad"
    assert r["stable"] == ["d", "b", "e", "a", "c"]

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

    # explained errors (errorhelp.py): a one-off wait is a warning, an alert is bad, each says cause, fix and who acts
    helped = [i for i in r["helped"] if i["text"].startswith("Error: ")]
    assert [i["level"] for i in helped] == ["warn", "bad"]
    assert "Fix: Nothing if it clears." in helped[0]["text"] and "usually clears by itself; first time" in helped[0]["text"]
    assert "needs you; 4 cycles in a row" in helped[1]["text"]
    assert not any("The last cycle had" in i["text"] for i in r["helped"])
    # no daily loss halt exists: say so when automatic entries are on, and only then
    assert any("no daily loss halt" in i["text"] and i["level"] == "warn" for i in r["halt"])
    assert not any("daily loss halt" in i["text"] for i in r["srvOk"])
    # worst-case money line: shown from account data, warns when most of equity is in open premium, unknown when missing
    low = [i for i in r["riskLow"] if "Worst case" in i["text"]]
    assert low and low[0]["level"] == "ok" and "10.0% of equity" in low[0]["text"]
    high = [i for i in r["riskHigh"] if "Worst case" in i["text"]]
    assert high and high[0]["level"] == "warn" and "60.0% of equity" in high[0]["text"]
    assert any("Money at risk unknown" in i["text"] and i["level"] == "warn" for i in r["riskMissing"])
    assert not any("Worst case" in i["text"] or "Money at risk" in i["text"] for i in r["none"])
    # calendar line: lists known closures from the exchange table only; absent data adds no line
    c = " ".join(i["text"] for i in r["cal"])
    assert "2026-11-26 market closed" in c and "2026-11-27 early close" in c and "not earnings or news" in c
    assert not any("Coming up" in i["text"] for i in r["none"])
    # strategy line: names the running strategy and warns that results are not split; unknown reads as a warning
    s = [i for i in r["strat"] if "Strategy in use" in i["text"]]
    assert s and "flow-otm 1.0" in s[0]["text"] and "not split by strategy" in s[0]["text"] and "no demonstrated edge" in s[0]["text"]
    assert any("strategy is running is unknown" in i["text"] and i["level"] == "warn" for i in r["none"])


def test_research_progress_line_is_text_only_and_honest_about_sample_size():
    """UX-1: the Desk shows shadow-book gate progress and the independent sample, never a missing report as fine."""
    import json, shutil, subprocess
    from pathlib import Path
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not installed")
    root = Path(__file__).resolve().parents[1] / "src" / "optplat" / "static"
    assert 'id="research-progress"' in (root / "index.html").read_text()
    assert '"/api/shadow"' in (root / "app.js").read_text() and "innerHTML" not in (root / "app.js").read_text()
    harness = """
const stub=()=>new Proxy(function(){},{get:(t,k)=>k==='matches'?false:(k==='style'||k==='classList'||k==='dataset')?stub():stub(),set:()=>true,apply:()=>stub()});
global.document={getElementById:()=>stub(),createElement:()=>stub(),querySelectorAll:()=>[],addEventListener(){},createTextNode:()=>stub()};
global.window={matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener(){}};global.location={hash:''};global.history={replaceState(){}};
global.sessionStorage={getItem:()=>'',setItem(){},removeItem(){}};global.fetch=()=>new Promise(()=>{});global.setInterval=()=>0;global.setTimeout=()=>0;
require(process.argv[1]);
const r=window.optplatResearch;
const gate={trading_days:20,followed:2000,underlyings:50,complete_pct:80,export_days_in_a_row:5};
const real={fictional:false,trading_days:3,followed:240,underlyings:12,complete_pct:null,independent_observations:36,gate};
console.log(JSON.stringify({none:r(null),real:r(real),fake:r({...real,fictional:true}),empty:r({...real,followed:0,independent_observations:0})}));
"""
    out = json.loads(subprocess.run([node, "-e", harness, str(root / "app.js")], capture_output=True, text=True, check=True).stdout)
    assert out["none"][0]["level"] == "warn" and "unknown" in out["none"][0]["text"]
    real = " ".join(i["text"] for i in out["real"])
    assert "3 of 20 trading days" in real and "240 of 2000 followed" in real and "n/a of paths complete" in real
    assert "36 independent observation(s)" in real and "not 240" in real and "export" in real
    assert any("FICTIONAL" in i["text"] and i["level"] == "warn" for i in out["fake"])
    assert any("Nothing is being followed" in i["text"] for i in out["empty"])


def test_decision_feed_verdicts_are_plain_and_unknown_is_never_fine():
    import json, shutil, subprocess
    from pathlib import Path
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not installed")
    root = Path(__file__).resolve().parents[1] / "src" / "optplat" / "static"
    assert "Routine skips are folded into one line" in (root / "index.html").read_text()  # renamed Activity (owner redesign 2026-11-25)
    harness = """
const stub=()=>new Proxy(function(){},{get:(t,k)=>k==='matches'?false:(k==='style'||k==='classList'||k==='dataset')?stub():stub(),set:()=>true,apply:()=>stub()});
global.document={getElementById:()=>stub(),createElement:()=>stub(),querySelectorAll:()=>[],addEventListener(){},createTextNode:()=>stub()};
global.window={matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener(){}};global.location={hash:''};global.history={replaceState(){}};
global.sessionStorage={getItem:()=>'',setItem(){},removeItem(){}};global.fetch=()=>new Promise(()=>{});global.setInterval=()=>0;global.setTimeout=()=>0;
require(process.argv[1]);
const v=window.optplatVerdict, t=window.optplatTally;
const L=[{kind:'ENTRY',disposition:'FILLED'},{kind:'COMMITTEE',disposition:'WOULD_ENTER'},{kind:'COMMITTEE',disposition:'WOULD_REJECT'},
 {kind:'ENTRY',disposition:'RISK_REJECTED'},{kind:'ENTRY',disposition:'NOT_CHOSEN_SIZE_CAP'},{kind:'ENTRY',disposition:'SKIPPED_HELD'},
 {kind:'EXIT',disposition:'FILLED'},{kind:'EXIT',disposition:'DEFERRED_MARKET_CLOSED'},{kind:'ENTRY',disposition:'MYSTERY'},{kind:'ENTRY'}];
console.log(JSON.stringify({v:L.map(v),tally:t(L),none:t([])}));
"""
    out = json.loads(subprocess.run([node, "-e", harness, str(root / "app.js")], capture_output=True, text=True, check=True).stdout)
    ids = [x["id"] for x in out["v"]]
    assert ids == ["taken", "opinion", "blocked", "blocked", "skipped", "skipped", "exit", "skipped", "other", "other"]
    assert out["v"][1]["text"].endswith("no order)")  # an opinion is never shown as a trade
    assert out["v"][8]["text"] == "Other: MYSTERY" and out["v"][9]["text"] == "Other: unknown"
    assert "1 taken" in out["tally"] and "1 opinion only" in out["tally"] and "2 other" in out["tally"]
    assert out["none"] == ""


def test_decision_feed_filter_groups_never_count_an_opinion_as_an_order():
    """UX-5: "Orders placed" holds only paper orders; opinions, blocks, skips and unknown lines each sit in their own group."""
    import json, shutil, subprocess
    from pathlib import Path
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not installed")
    root = Path(__file__).resolve().parents[1] / "src" / "optplat" / "static"
    js = (root / "app.js").read_text()
    assert "innerHTML" not in js and "Orders placed (paper)" in js
    harness = """
const stub=()=>new Proxy(function(){},{get:(t,k)=>k==='matches'?false:(k==='style'||k==='classList'||k==='dataset')?stub():stub(),set:()=>true,apply:()=>stub()});
global.document={getElementById:()=>stub(),createElement:()=>stub(),querySelectorAll:()=>[],addEventListener(){},createTextNode:()=>stub()};
global.window={matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener(){}};global.location={hash:''};global.history={replaceState(){}};
global.sessionStorage={getItem:()=>'',setItem(){},removeItem(){}};global.fetch=()=>new Promise(()=>{});global.setInterval=()=>0;global.setTimeout=()=>0;
require(process.argv[1]);
const f=window.optplatDecisionFilter;
const L=[{kind:'ENTRY',disposition:'FILLED'},{kind:'EXIT',disposition:'FILLED'},{kind:'COMMITTEE',disposition:'WOULD_ENTER'},
 {kind:'ENTRY',disposition:'RISK_REJECTED'},{kind:'ENTRY',disposition:'SKIPPED_HELD'},{kind:'ENTRY',disposition:'SUBMITTED'},{kind:'ENTRY',disposition:'MYSTERY'}];
const n=(id)=>f(L,id).map((d)=>d.disposition);
console.log(JSON.stringify({all:n('all'),placed:n('placed'),notaken:n('notaken'),opinion:n('opinion'),other:n('other'),bad:n('nope'),none:f(null,'placed')}));
"""
    out = json.loads(subprocess.run([node, "-e", harness, str(root / "app.js")], capture_output=True, text=True, check=True).stdout)
    assert len(out["all"]) == 7 and out["bad"] == out["all"] and out["none"] == []
    assert out["placed"] == ["FILLED", "FILLED", "SUBMITTED"] and "WOULD_ENTER" not in out["placed"]
    assert out["notaken"] == ["RISK_REJECTED", "SKIPPED_HELD"] and out["opinion"] == ["WOULD_ENTER"] and out["other"] == ["MYSTERY"]
