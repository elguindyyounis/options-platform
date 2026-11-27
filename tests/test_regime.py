from datetime import datetime, timezone

from fastapi.testclient import TestClient

from optplat import regime
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, Runner, TradingEngine
from optplat.marketdata import DemoDataProvider
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy

H = {"X-API-Token": "t" * 24}


def drift(n, start, end):
    return [start + (end - start) * i / (n - 1) for i in range(n)]


def selloff_then_bounce():
    c = drift(40, 100.0, 100.0) + drift(15, 100.0, 88.0)  # a 12% slide
    return c + [c[-1] * 1.02]  # then a +2% day


def test_deep_drop_then_bounce_blocks_puts_not_calls():
    r = regime.read_regime(selloff_then_bounce())
    assert r.block_puts and not r.block_calls and r.label == "oversold_bounce"
    assert regime.read_regime(selloff_then_bounce()).check("P")[0] is False
    assert r.check("C")[0] is True and "20-day high" in " ".join(r.oversold)


def test_calm_uptrend_blocks_nothing():
    r = regime.read_regime(drift(60, 100.0, 104.0))
    assert not r.block_puts and not r.block_calls and r.label == "uptrend"


def test_overbought_and_selloff_block_calls():
    up = drift(40, 100.0, 100.0) + drift(15, 100.0, 112.0)
    r = regime.read_regime(up + [up[-1] * 0.985])
    assert r.block_calls and not r.block_puts


def test_one_signal_alone_does_not_block():
    r = regime.read_regime(drift(60, 100.0, 100.0), vix=31.0)  # a high VIX on its own is one signal
    assert r.oversold == ("VIX 31",) and not r.block_puts


def test_too_few_bars_is_unknown_and_never_blocks():
    assert regime.read_regime([100.0] * 10) is None
    src = regime.RegimeSource(lambda: [100.0] * 10)
    assert src.allows("P") == (True, "", None)
    boom = regime.RegimeSource(lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert boom.allows("P")[0] is True


def test_implausible_vix_is_ignored_and_real_one_counts():
    assert not any("VIX" in x for x in regime.read_regime(drift(60, 100, 100), vix=414.0).oversold)
    assert any("VIX 35" in x for x in regime.read_regime(drift(60, 100, 100), vix=35.0).oversold)


def test_breadth_washout_and_thrust_count():
    r = regime.read_regime(drift(60, 100, 100), breadth_up_pct=95.0)
    assert r.bounce and not r.block_puts  # one signal only
    r2 = regime.read_regime(selloff_then_bounce(), breadth_up_pct=92.0)
    assert r2.block_puts


def test_switch_off_with_env(monkeypatch):
    monkeypatch.setenv("OPTPLAT_REGIME_GUARD", "0")
    assert regime.RegimeSource(selloff_then_bounce).allows("P")[0] is True


def test_source_caches_for_five_minutes():
    calls = []
    now = [datetime(2026, 11, 24, 15, tzinfo=timezone.utc)]
    src = regime.RegimeSource(lambda: calls.append(1) or selloff_then_bounce(), lambda: now[0])
    src.read(); src.read()
    assert len(calls) == 1


def test_engine_blocks_and_journals_a_put_into_a_bounce():
    # A fixed clock: the fictional demo market moves with the wall clock, and on a day it trends up the strategy proposes
    # only calls, so a put block could never show. Same assertions as before; only the date is pinned.
    now = datetime(2026, 11, 24, 15, tzinfo=timezone.utc)
    clock = lambda: now  # noqa: E731
    m = OrderManager(SimBroker(), Store(":memory:"))
    e = TradingEngine(m, DemoDataProvider(clock=clock), LiquidTrendStrategy(), default_config=EngineConfig(), clock=clock)
    e.regime = regime.RegimeSource(selloff_then_bounce, clock)
    app = create_app(m, "t" * 24, e, Runner(e))
    with TestClient(app) as c:
        c.put("/api/engine/config", json={"enforce_market_hours": False, "auto_entries": True}, headers=H)
        rep = c.post("/api/engine/cycle", headers=H).json()
        blocked = [x for x in rep["entries"] if x["result"] == "BLOCKED_REGIME"]
        assert blocked and "puts blocked" in blocked[0]["reason"]
        assert not any(x["result"] == "FILLED" and "-P-" in str(x) for x in rep["entries"])
        j = c.get("/api/journal?limit=50", headers=H).json()
        assert any(d.get("disposition") == "SKIPPED_REGIME" for d in j)


# ---- Desk line (UX-9): display only, never an all-clear when the reading is missing ----
import json  # noqa: E402
from datetime import timedelta  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

NOW = datetime(2026, 11, 24, 15, tzinfo=timezone.utc)


def test_describe_known_blocked_reading_names_the_rule_and_authorizes_nothing():
    d = regime.describe(regime.RegimeSource(selloff_then_bounce, lambda: NOW), data_source="demo daily bars (SPY)", fictional=True)
    assert d["state"] == "known" and d["puts_allowed"] is False and d["calls_allowed"] is True
    assert "New puts blocked" in d["reasons"][0] and d["authorizes_orders"] is False and d["fictional"] is True and "not an edge" in d["note"]


def test_describe_unknown_and_off_never_look_like_a_block_or_a_reading(monkeypatch):
    d = regime.describe(regime.RegimeSource(lambda: [100.0] * 10, lambda: NOW), data_source="x", fictional=False)
    assert d["state"] == "unknown" and d["puts_allowed"] and d["calls_allowed"] and d["label"] is None
    monkeypatch.setenv("OPTPLAT_REGIME_GUARD", "0")
    assert regime.describe(regime.RegimeSource(selloff_then_bounce, lambda: NOW), data_source="x", fictional=False)["state"] == "off"


def test_regime_endpoint_is_authenticated_and_labels_fictional_data():
    clock = lambda: NOW  # noqa: E731
    m = OrderManager(SimBroker(), Store(":memory:"))
    e = TradingEngine(m, DemoDataProvider(clock=clock), LiquidTrendStrategy(), default_config=EngineConfig(), clock=clock)
    e.regime = regime.RegimeSource(selloff_then_bounce, clock)
    with TestClient(create_app(m, "t" * 24, e, Runner(e))) as c:
        assert c.get("/api/regime").status_code in (401, 403)
        j = c.get("/api/regime", headers=H).json()
        assert j["puts_allowed"] is False and j["fictional"] is True and "demo-synthetic" in j["data_source"]


STATIC = Path(__file__).resolve().parents[1] / "src" / "optplat" / "static"
HARNESS = """
const stub=()=>new Proxy(function(){},{get:(t,k)=>k==='matches'?false:(k==='style'||k==='classList'||k==='dataset')?stub():stub(),set:()=>true,apply:()=>stub()});
global.document={getElementById:()=>stub(),createElement:()=>stub(),querySelectorAll:()=>[],addEventListener(){},createTextNode:()=>stub()};
global.window={matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener(){}};global.location={hash:''};global.history={replaceState(){}};
global.sessionStorage={getItem:()=>'',setItem(){},removeItem(){}};global.fetch=()=>new Promise(()=>{});global.setInterval=()=>0;global.setTimeout=()=>0;
require(process.argv[1]);const T=window.optplatRegimeText;
const base={guard_on:true,data_source:'demo daily bars (SPY)',fictional:false,facts:{day_pct:0.4,rsi14:55}};
console.log(JSON.stringify([T(null),T({...base,state:'off'}),T({...base,state:'unknown',fictional:true}),
 T({...base,state:'known',label:'uptrend',puts_allowed:true,calls_allowed:true}),
 T({...base,state:'known',label:'oversold_bounce',puts_allowed:false,calls_allowed:true,reasons:['New puts blocked: market is oversold bounce (RSI 28)']})]));
"""


def test_desk_line_never_reads_unknown_as_all_clear():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    out = json.loads(subprocess.run([node, "-e", HARNESS, str(STATIC / "app.js")], capture_output=True, text=True, check=True).stdout)
    none, off, unk, ok, blocked = out
    assert none["text"] == "" and off["cls"] == "warn" and "switched off" in off["text"]
    assert unk["cls"] == "warn" and "not an all-clear" in unk["text"] and "Fictional demo data" in unk["text"]
    assert ok["cls"] == "ok" and "uptrend" in ok["text"] and "not an edge" in ok["text"]
    assert blocked["cls"] == "warn" and "New puts blocked" in blocked["text"] and "exits are untouched" in blocked["text"]


# ---- UX-11: held-back count (display only, a minimum, same data kind as the page) ----
HB_HARNESS = HARNESS.replace(
    "console.log(JSON.stringify([T(null)",
    "const hb=(h)=>T({...base,state:'known',label:'uptrend',puts_allowed:true,calls_allowed:true,held_back:h}).text;\n"
    "console.log(JSON.stringify([hb({hours:24,total:0,puts:0,calls:0}),hb({hours:24,total:1,puts:1,calls:0}),hb({hours:24,total:5,puts:4,calls:1}),T(null)",
)


def _log(store, ts, right, disposition="SKIPPED_REGIME", fictional=False, kind="ENTRY"):
    store.record_decision(ts, "SPY", kind, disposition, "SPY   261127P00600000", "s", 1.0, None, fictional, {"contract": {"right": right}})


def test_held_back_counts_recent_regime_lines_only_for_this_data_kind():
    store = Store(":memory:")
    _log(store, NOW - timedelta(hours=1), "P")
    _log(store, NOW - timedelta(hours=2), "P")
    _log(store, NOW - timedelta(hours=3), "C")
    _log(store, NOW - timedelta(hours=30), "P")  # too old
    _log(store, NOW - timedelta(hours=1), "P", fictional=True)  # other data kind
    _log(store, NOW - timedelta(hours=1), "P", disposition="SKIPPED_HELD")  # not a regime hold
    h = regime.held_back(store, NOW, fictional=False)
    assert (h["puts"], h["calls"], h["total"], h["lower_bound"]) == (2, 1, 3, True)
    assert regime.held_back(store, NOW, fictional=True)["total"] == 1
    assert regime.held_back(Store(":memory:"), NOW, fictional=False)["total"] == 0


def test_regime_endpoint_includes_held_back_and_desk_says_minimum():
    clock = lambda: NOW  # noqa: E731
    m = OrderManager(SimBroker(), Store(":memory:"))
    e = TradingEngine(m, DemoDataProvider(clock=clock), LiquidTrendStrategy(), default_config=EngineConfig(), clock=clock)
    e.regime = regime.RegimeSource(selloff_then_bounce, clock)
    _log(e.store, NOW - timedelta(hours=1), "P", fictional=True)
    with TestClient(create_app(m, "t" * 24, e, Runner(e))) as c:
        assert c.get("/api/regime", headers=H).json()["held_back"]["total"] == 1
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    none_yet, one, many, _ = json.loads(subprocess.run([node, "-e", HB_HARNESS, str(STATIC / "app.js")], capture_output=True, text=True, check=True).stdout)[:4]
    assert "Nothing recorded as held back" in none_yet
    assert "at least 1 new entry (1 put, 0 calls)" in one and "minimum" in one
    assert "at least 5 new entries (4 puts, 1 call)" in many
