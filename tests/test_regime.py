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
    m = OrderManager(SimBroker(), Store(":memory:"))
    e = TradingEngine(m, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    e.regime = regime.RegimeSource(selloff_then_bounce)
    app = create_app(m, "t" * 24, e, Runner(e))
    with TestClient(app) as c:
        c.put("/api/engine/config", json={"enforce_market_hours": False, "auto_entries": True}, headers=H)
        rep = c.post("/api/engine/cycle", headers=H).json()
        blocked = [x for x in rep["entries"] if x["result"] == "BLOCKED_REGIME"]
        assert blocked and "puts blocked" in blocked[0]["reason"]
        assert not any(x["result"] == "FILLED" and "-P-" in str(x) for x in rep["entries"])
        j = c.get("/api/journal?limit=50", headers=H).json()
        assert any(d.get("disposition") == "SKIPPED_REGIME" for d in j)
