import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, Runner, TradingEngine
from optplat.exposure import bs_greeks, open_exposure
from optplat.marketdata import DemoDataProvider
from optplat.models import Right
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy

NOW = datetime(2026, 11, 27, 15, tzinfo=timezone.utc)
H = {"X-API-Token": "t" * 24}


def payload(right="C", iv=0.3, expiry="2026-12-18", spot=100.0, strike=100.0):
    return {"contract": "X", "right": right, "strike": strike, "expiry": expiry, "iv": iv, "chain_underlying": spot, "multiplier": 100}


def test_call_put_greeks_match_known_relations():
    c, p = bs_greeks(Right.CALL, 100, 100, 0.25, 0.3), bs_greeks(Right.PUT, 100, 100, 0.25, 0.3)
    assert 0.5 < c["delta"] < 0.6 and abs((c["delta"] - p["delta"]) - 1) < 1e-9  # call delta minus put delta is 1
    assert c["gamma"] == p["gamma"] and c["vega_per_point"] == p["vega_per_point"] > 0 and c["theta_per_day"] < 0
    assert bs_greeks(Right.CALL, 100, 100, 0.0, 0.3) is None and bs_greeks(Right.CALL, 100, 100, 0.25, 0.0) is None


def test_exposure_sums_open_trades_signs_by_side_and_counts_what_it_cannot_value():
    s = Store(":memory:")
    s.lane_open("L", "AAA", NOW, 2.0, 2, False, payload("C"))
    s.lane_open("L", "AAA", NOW, 2.0, 1, False, payload("P"))
    s.lane_open("L", "BBB", NOW, 2.0, 1, False, payload("C", iv=0.0))           # no IV: left out and counted
    s.lane_open("L", "CCC", NOW, 2.0, 1, False, payload("C", expiry="2026-11-01"))  # already expired: left out and counted
    done = s.lane_open("L", "DDD", NOW, 2.0, 1, False, payload("C"))
    s.lane_close(done, NOW, 3.0, "target", {})                                  # closed trades do not count
    s.lane_open("L", "EEE", NOW, 100.0, 5, False, {"kind": "stock"})            # stock-lane trade: no greeks, not counted
    x = open_exposure(s, ["L"], False, NOW)
    assert x["valued"] == 2 and x["unknown"] == 2 and x["complete"] is False
    assert x["delta_by_symbol"] == {"AAA": pytest.approx(x["net_delta_shares"], abs=0.2)}
    assert x["net_delta_shares"] > 0 and x["theta_usd_per_day"] < 0 and x["vega_usd_per_point"] > 0
    assert "entry" in x["note"] and "Display only" in x["note"]


def test_nothing_open_is_empty_not_an_error():
    x = open_exposure(Store(":memory:"), ["L"], True, NOW)
    assert x["valued"] == 0 and x["unknown"] == 0 and x["net_delta_shares"] == 0 and x["fictional"] is True


def test_endpoint_needs_auth_and_labels_fictional():
    clock = lambda: NOW  # noqa: E731
    m = OrderManager(SimBroker(), Store(":memory:"))
    e = TradingEngine(m, DemoDataProvider(clock=clock), LiquidTrendStrategy(), default_config=EngineConfig(), clock=clock)
    e.store.lane_open("shortterm-ema9-vwap", "AAA", NOW, 2.0, 1, True, payload("C"))
    with TestClient(create_app(m, "t" * 24, e, Runner(e))) as c:
        assert c.get("/api/exposure").status_code in (401, 403)
        j = c.get("/api/exposure", headers=H).json()
        assert j["fictional"] is True and j["valued"] + j["unknown"] <= 1


HARNESS = """
const stub=()=>new Proxy(function(){},{get:(t,k)=>k==='matches'?false:(k==='style'||k==='classList'||k==='dataset')?stub():stub(),set:()=>true,apply:()=>stub()});
global.document={getElementById:()=>stub(),createElement:()=>stub(),querySelectorAll:()=>[],addEventListener(){},createTextNode:()=>stub()};
global.window={matchMedia:()=>({matches:false,addEventListener(){}}),addEventListener(){}};global.location={hash:''};global.history={replaceState(){}};
global.sessionStorage={getItem:()=>'',setItem(){},removeItem(){}};global.fetch=()=>new Promise(()=>{});global.setInterval=()=>0;global.setTimeout=()=>0;
require(process.argv[1]);const T=window.optplatExposureText;
const b={fictional:false,net_delta_shares:12.5,theta_usd_per_day:-30,vega_usd_per_point:8};
console.log(JSON.stringify([T(null),T({...b,valued:0,unknown:0}),T({...b,valued:0,unknown:2}),T({...b,valued:3,unknown:0}),T({...b,valued:3,unknown:1,fictional:true})]));
"""


def test_desk_line_flags_partial_and_unvalued_exposure():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    app = Path(__file__).resolve().parents[1] / "src" / "optplat" / "static" / "app.js"
    none, empty, unvalued, full, part = json.loads(subprocess.run([node, "-e", HARNESS, str(app)], capture_output=True, text=True, check=True).stdout)
    assert none["text"] == "" and empty["text"] == ""
    assert unvalued["cls"] == "warn" and "unknown" in unvalued["text"]
    assert full["cls"] == "" and "net delta +12.5 shares" in full["text"] and "Approximate" in full["text"]
    assert part["cls"] == "warn" and "Partial" in part["text"] and "Fictional demo data" in part["text"]
