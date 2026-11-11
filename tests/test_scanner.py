from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from helpers import NOW
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, TradingEngine
from optplat.marketdata import Bar, ChainRow, DemoDataProvider, StaticDataProvider
from optplat.models import OptionContract, Right
from optplat.orders import OrderManager
from optplat.scanner import (MIN_UNUSUAL_VOLUME, UNIVERSE, Scanner, completed_bars, rank_active, unusual_contracts)
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy
from test_engine import EXPIRY, snapshot

TODAY = NOW.date()  # a Monday, 10:00 New York time: the regular session is open


def bars(vol_last=2_000_000, base=1_000_000, n=25, close=100.0, today_volume=None):
    days = [TODAY - timedelta(days=n - i) for i in range(n)]
    out = [Bar(d, close, base) for d in days[:-1]] + [Bar(days[-1], close * 1.02, vol_last)]
    if today_volume is not None:
        out.append(Bar(TODAY, close, today_volume))
    return out


# ------------------------------------------------------------ ranking
def test_names_are_ranked_by_dollar_volume_with_relative_volume_and_a_surge_flag():
    raw = {"BIG": bars(vol_last=5_000_000, close=200.0), "SURGE": bars(vol_last=3_000_000, base=1_000_000), "QUIET": bars(vol_last=900_000)}
    rows = rank_active(raw, NOW)
    assert [r["symbol"] for r in rows] == ["BIG", "SURGE", "QUIET"] and [r["rank"] for r in rows] == [1, 2, 3]
    big = rows[0]
    assert big["dollar_volume"] == round(204.0 * 5_000_000) and big["relative_volume"] == 5.0 and big["surge"]
    assert not rows[2]["surge"] and rows[2]["change_pct"] == 2.0


def test_todays_partial_bar_is_dropped_while_the_session_is_open():
    raw = bars(today_volume=10)  # a tiny partial volume must not make the name look dead
    assert completed_bars(raw, NOW)[-1].day != TODAY
    assert rank_active({"X": raw}, NOW)[0]["volume"] == 2_000_000
    closed = NOW.replace(hour=22)  # after the close the day is complete
    assert completed_bars(raw, closed)[-1].day == TODAY


def test_too_little_or_bad_history_is_skipped_not_guessed():
    short = bars(n=10)
    bad = bars()
    bad[-3] = Bar(bad[-3].day, float("nan"), 5)
    rows = rank_active({"SHORT": short, "BAD": bad, "OK": bars()}, NOW)
    assert [r["symbol"] for r in rows] == ["BAD", "OK"] or [r["symbol"] for r in rows] == ["OK", "BAD"]
    assert "SHORT" not in [r["symbol"] for r in rows]
    assert rank_active({"BAD": [Bar(TODAY - timedelta(days=i), -1.0, 5) for i in range(30)]}, NOW) == []


# ------------------------------------------------------------ unusual activity
def snap_with(*rows):
    return snapshot().__class__(**{**snapshot().__dict__, "rows": tuple(rows)})


def row(volume, oi, bid=4.9, ask=5.1, strike=160.0, right=Right.CALL, days=60):
    return ChainRow(OptionContract("AAA", TODAY + timedelta(days=days), right, strike), bid, ask, volume, oi, 0.3)


def flagged(*rows):
    return unusual_contracts(snap_with(*rows), NOW)


def test_thresholds_volume_ratio_and_zero_open_interest():
    assert flagged(row(MIN_UNUSUAL_VOLUME - 1, 10)) == []
    hit = flagged(row(150, 40))
    assert len(hit) == 1 and hit[0]["volume_oi_ratio"] == 3.75
    assert flagged(row(150, 52)) == []  # 2.88x: ordinary turnover
    zero = flagged(row(500, 0))
    assert len(zero) == 1 and zero[0]["volume_oi_ratio"] is None and zero[0]["oi_state"] == "REPORTED_ZERO"
    assert flagged(row(499, 0)) == [] and flagged(row(499, None)) == []
    assert flagged(row(500, None))[0]["oi_state"] == "MISSING"


def test_crossed_or_zero_ask_quotes_are_never_flagged_and_ratio_is_never_infinite():
    assert flagged(row(900, 10, bid=5.2, ask=5.0)) == [] and flagged(row(900, 10, bid=0.0, ask=0.0)) == []
    for r in flagged(row(900, 0), row(900, None), row(900, 100)):
        assert r["volume_oi_ratio"] is None or r["volume_oi_ratio"] < 1e6


def test_wide_or_thin_or_short_dated_contracts_are_observe_only():
    good = flagged(row(2000, 500, bid=4.95, ask=5.05))[0]
    assert good["decision"] == "REVIEWABLE" and good["liquidity_tier"] in ("A", "B")
    wide = flagged(row(2000, 500, bid=3.0, ask=5.0))[0]
    assert wide["decision"] == "OBSERVE_ONLY" and wide["why_observe_only"] == "wide or thin market"
    near = flagged(row(2000, 500, bid=4.95, ask=5.05, days=3))[0]
    assert near["decision"] == "OBSERVE_ONLY" and "expiry" in near["why_observe_only"]
    assert good["quoted_turnover_usd"] == round(5.05 * 2000 * 100)
    thin = flagged(row(1000, 200, bid=4.95, ask=5.05))[0]  # open interest 200 is thin by the liquidity tiers
    assert thin["decision"] == "OBSERVE_ONLY"


# ------------------------------------------------------------ the scan job
def make(provider=None, **kw):
    store = Store(":memory:")
    prov = provider or DemoDataProvider(clock=lambda: NOW)
    return Scanner(prov, store, clock=lambda: NOW, **kw), store


def test_a_demo_scan_ranks_names_reads_chains_and_is_labelled_fictional():
    sc, store = make()
    out = sc.run()
    assert out["fictional"] is True and out["source"] == "demo-synthetic"
    assert 0 < len(out["active_names"]) <= 25 and out["coverage"]["chains_scanned"] > 0
    assert out["active_names"][0]["dollar_volume"] >= out["active_names"][-1]["dollar_volume"]
    assert out["option_names"] == sorted(out["option_names"], key=lambda r: -r["total_volume"])
    assert out["limitations"] and "thresholds" in out
    assert store.latest_scan(True)["as_of"] == NOW.isoformat() and store.latest_scan(False) is None  # kept apart


def test_a_provider_without_bars_says_so_and_ranks_nothing():
    sc, store = make(StaticDataProvider(lambda: NOW))
    out = sc.run()
    assert out["active_names"] == [] and any("daily bars unavailable" in e for e in out["errors"])
    assert store.latest_scan(False)["errors"]


def test_a_time_budget_stops_chain_reads_but_keeps_the_ranking():
    sc, _ = make(budget_s=-1.0)
    out = sc.run()
    assert out["active_names"] and any("time budget" in e for e in out["errors"]) and out["coverage"]["chains_scanned"] == 0


def test_a_chain_that_fails_or_is_rejected_is_reported_not_hidden():
    class Flaky(DemoDataProvider):
        def snapshot(self, symbol):
            raise RuntimeError("rate limited")

    sc, _ = make(Flaky(clock=lambda: NOW))
    out = sc.run()
    assert out["coverage"]["chains_failed"] > 0 and any("chain unavailable" in e for e in out["errors"])


def test_the_universe_is_a_fixed_list_without_duplicates():
    assert len(UNIVERSE) == len(set(UNIVERSE)) and "SPY" in UNIVERSE and len(UNIVERSE) > 50


# ------------------------------------------------------------ engine and API
def build_engine():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    return manager, engine


def test_scan_interval_is_validated_and_off_by_default():
    _, engine = build_engine()
    assert engine.config().scan_interval_s == 0
    for bad in (1, 599, 90_000):
        with pytest.raises(ValueError, match="scan_interval_s"):
            engine.set_config({"scan_interval_s": bad})
    assert engine.set_config({"scan_interval_s": 600}).scan_interval_s == 600


def test_maybe_scan_respects_the_interval():
    _, engine = build_engine()
    engine.maybe_scan()
    assert engine.scanner.latest() is None and not engine.scanner.running()  # off
    engine.set_config({"scan_interval_s": 600})
    engine.maybe_scan()
    engine.scanner._thread.join(timeout=30)
    first = engine.scanner.latest()
    assert first is not None
    engine.maybe_scan()  # due again only after the interval
    assert not engine.scanner.running()


def test_scan_endpoints_need_the_token_and_return_the_latest_result():
    manager, engine = build_engine()
    tok = "t" * 24
    with TestClient(create_app(manager, tok, engine)) as c:
        assert c.get("/api/scan").status_code == 401 and c.post("/api/scan/run").status_code == 401
        h = {"X-API-Token": tok}
        assert c.get("/api/scan", headers=h).json()["result"] is None
        assert c.post("/api/scan/run", headers=h).json()["started"] is True
        engine.scanner._thread.join(timeout=30)
        body = c.get("/api/scan", headers=h).json()
        assert body["result"]["active_names"] and body["status"]["running"] is False
        assert c.put("/api/engine/config", json={"scan_interval_s": 1200}, headers=h).json()["scan_interval_s"] == 1200
