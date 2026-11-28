"""UX-12: entries looked at and not taken, counted by reason (display only)."""
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, Runner, TradingEngine
from optplat.marketdata import DemoDataProvider
from optplat.nottaken import REASONS, not_taken
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy

NOW = datetime(2026, 11, 27, 15, 0, tzinfo=timezone.utc)
H = {"X-API-Token": "t" * 24}


def put(store, ts, disp, fictional=True, kind="ENTRY"):
    store.record_decision(ts, "SPY", kind, disp, "SPY261218P00600000", "s:1", 1.0, None, fictional, {"contract": {"right": "P"}})


def test_counts_by_reason_newest_window_and_data_kind():
    s = Store(":memory:")
    put(s, NOW - timedelta(hours=1), "SKIPPED_REGIME")
    put(s, NOW - timedelta(hours=2), "SKIPPED_REGIME")
    put(s, NOW - timedelta(hours=3), "NOT_CHOSEN_SIZE_CAP")
    put(s, NOW - timedelta(hours=30), "SKIPPED_HELD")            # outside 24 h
    put(s, NOW - timedelta(hours=1), "SKIPPED_COOLDOWN", False)  # real data, page is demo
    put(s, NOW - timedelta(hours=1), "FILLED")                   # taken, not a skip
    put(s, NOW - timedelta(hours=1), "SKIPPED_REGIME", kind="EXIT")
    n = not_taken(s, NOW, fictional=True)
    assert n["total"] == 3 and n["lower_bound"] is True and n["fictional"] is True
    assert [(r["disposition"], r["count"]) for r in n["reasons"]] == [("SKIPPED_REGIME", 2), ("NOT_CHOSEN_SIZE_CAP", 1)]
    real = not_taken(s, NOW, fictional=False)
    assert real["total"] == 1 and real["reasons"][0]["disposition"] == "SKIPPED_COOLDOWN"


def test_reasons_are_only_dispositions_the_engine_writes():
    src = (Path(__file__).resolve().parents[1] / "src" / "optplat" / "engine.py").read_text()
    for k in REASONS:
        assert '"' + k + '"' in src, k


def test_endpoint_is_authenticated():
    clock = lambda: NOW  # noqa: E731
    m = OrderManager(SimBroker(), Store(":memory:"))
    e = TradingEngine(m, DemoDataProvider(clock=clock), LiquidTrendStrategy(), default_config=EngineConfig(), clock=clock)
    put(e.store, NOW - timedelta(hours=1), "NOT_CHOSEN")
    with TestClient(create_app(m, "t" * 24, e, Runner(e))) as c:
        assert c.get("/api/not-taken").status_code in (401, 403)
        j = c.get("/api/not-taken", headers=H).json()
        assert j["total"] == 1 and j["fictional"] is True


HARNESS = """
const stub=()=>new Proxy(function(){},{get:(t,k)=>k==='matches'?false:(k==='style'||k==='classList'||k==='dataset')?stub():stub(),set:()=>true,apply:()=>stub()});
global.document={getElementById:()=>stub(),createElement:()=>stub(),querySelectorAll:()=>[],addEventListener(){},createTextNode:()=>stub()};
global.window={matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener(){}};global.location={hash:''};global.history={replaceState(){}};
global.sessionStorage={getItem:()=>'',setItem(){},removeItem(){}};global.fetch=()=>new Promise(()=>{});global.setInterval=()=>0;global.setTimeout=()=>0;
require(process.argv[1]);const T=window.optplatNotTakenText;
console.log(JSON.stringify([T(null),T({hours:24,total:0,reasons:[],fictional:false}),
 T({hours:24,total:3,fictional:true,reasons:[{count:2,reason:'market-regime guard held it back'},{count:1,reason:'did not fit the size cap'}]})]));
"""


def test_strip_text_is_a_minimum_and_never_an_all_clear():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    app = Path(__file__).resolve().parents[1] / "src" / "optplat" / "static" / "app.js"
    none, zero, some = json.loads(subprocess.run([node, "-e", HARNESS, str(app)], capture_output=True, text=True, check=True).stdout)
    assert none["text"] == ""
    assert "Nothing recorded" in zero["text"] and "may simply have had no candidate" in zero["text"]
    assert some["cls"] == "warn" and "at least 3" in some["text"] and "2 market-regime guard held it back" in some["text"]
    assert "minimums" in some["text"] and "Fictional demo data" in some["text"]
