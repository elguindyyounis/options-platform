from datetime import timedelta

from fastapi.testclient import TestClient

from helpers import NOW
from optplat import context
from optplat.api import create_app
from optplat.marketdata import ChainRow, MarketSnapshot
from optplat.models import OptionContract, Right
from test_scanner import build_engine

EXP = NOW.date() + timedelta(days=14)


def row(right, strike, bid=1.0, ask=1.2, vol=100, oi=1000, iv=0.3, expiry=EXP, sym="SPY"):
    return ChainRow(OptionContract(sym, expiry, right, strike), bid, ask, vol, oi, iv)


def snap(rows, spot=100.0, sym="SPY"):
    return MarketSnapshot(sym, spot, (99.0, 100.0), tuple(rows), NOW, "test", True, True)


def test_sentiment_reading_bins_and_unknown():
    assert context.reading(None) == "UNKNOWN"
    assert context.reading(1.3) == "CALL_HEAVY" and context.reading(0.7) == "PUT_HEAVY" and context.reading(1.0) == "BALANCED"
    s = context.sentiment_row(snap([row(Right.CALL, 100, vol=300), row(Right.PUT, 100, vol=100, bid=2.0, ask=2.2)]))
    assert s["call_put_volume_ratio"] == 3.0 and s["reading"] == "CALL_HEAVY" and s["call_volume"] == 300
    assert s["call_premium_usd"] == round(1.1 * 300 * 100) and s["call_put_premium_ratio"] < 3.0  # puts cost more per contract
    no_puts = context.sentiment_row(snap([row(Right.CALL, 100)]))
    assert no_puts["call_put_volume_ratio"] is None and no_puts["reading"] == "UNKNOWN"


def test_levels_find_walls_on_the_right_side_of_spot_and_never_guess_without_data():
    rows = [row(Right.CALL, 105, oi=9000), row(Right.CALL, 110, oi=2000), row(Right.PUT, 95, oi=8000),
            row(Right.PUT, 90, oi=1000), row(Right.CALL, 95, oi=50000)]  # big call below spot must not become the call wall
    lv = context.levels(snap(rows), NOW)
    assert lv["call_wall"] == 105.0 and lv["put_wall"] == 95.0
    by = {p["strike"]: p for p in lv["profile"]}
    assert by[105.0]["call_musd"] > 0 > by[95.0]["put_musd"] and by[95.0]["net_musd"] > 0  # the large call at 95 dominates there
    empty = context.levels(snap([row(Right.CALL, 100, iv=None), row(Right.PUT, 100, oi=0), row(Right.CALL, 200)]), NOW)
    assert empty["profile"] == [] and empty["call_wall"] is None and empty["put_wall"] is None and empty["rows_skipped"] == 3


def test_expected_move_uses_nearest_complete_straddle():
    rows = [row(Right.CALL, 100, bid=2.0, ask=2.2), row(Right.PUT, 100, bid=1.8, ask=2.0),
            row(Right.CALL, 100, bid=5, ask=5.2, expiry=EXP + timedelta(days=30)),
            row(Right.CALL, 100, bid=0.5, ask=0.6, expiry=NOW.date() + timedelta(days=1))]  # too near: skipped
    em = context.expected_move(snap(rows), NOW.date())
    assert em["status"] == "OK" and em["pct"] == 4.0 and em["expiry"] == EXP.isoformat()
    assert context.expected_move(snap([row(Right.CALL, 100)]), NOW.date())["status"] == "INCOMPLETE_STRADDLE"
    assert context.expected_move(snap([]), NOW.date())["status"] == "NO_USABLE_EXPIRY"


def test_build_orders_by_core_list_names_missing_and_summarises_groups():
    a = snap([row(Right.CALL, 100, vol=200), row(Right.PUT, 100, vol=100)], sym="QQQ")
    b = snap([row(Right.CALL, 100, vol=50), row(Right.PUT, 100, vol=100)], sym="SPY")
    out = context.build([a, b], NOW, True)
    assert [r["symbol"] for r in out["rows"]] == ["SPY", "QQQ"] and out["fictional"] is True
    assert "IWM" in out["missing"] and "SPY" not in out["missing"]
    idx = out["groups"]["index"]
    assert idx["names"] == 2 and idx["call_volume"] == 250 and idx["put_volume"] == 200 and idx["call_heavy_names"] == 1
    assert idx["put_heavy_names"] == 1 and any("hedging" in n for n in out["notes"])


def test_context_endpoint_needs_token_and_marks_unknown_earnings_as_null():
    manager, engine = build_engine()
    tok = "t" * 24
    with TestClient(create_app(manager, tok, engine)) as c:
        assert c.get("/api/context").status_code == 401
        h = {"X-API-Token": tok}
        body = c.get("/api/context", headers=h).json()
        assert body["rows"] == [] and set(body["missing"]) == set(context.CORE)  # no scan yet: nothing invented
        assert all(v is None for v in body["earnings"].values())  # no earnings source wired in this fixture
        c.post("/api/scan/run", headers=h)
        engine.scanner._thread.join(timeout=30)
        assert "market_context" in engine.scanner.latest()
