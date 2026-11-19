from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from optplat import callouts, shadow
from optplat.marketdata import ChainRow, MarketSnapshot
from optplat.models import OptionContract, Right
from optplat.store import Store

DAY = date(2026, 11, 19)
EXP = date(2026, 12, 24)


def add(s, **kw):
    args = dict(symbol="baba", expiry=EXP, right="c", strike=90, price=3.5, size="Large", source="BuddyBear", day=DAY)
    args.update(kw)
    return callouts.record(s, **args)


def test_record_normalises_and_dedupes_and_marks_posted_price():
    s = Store(":memory:")
    assert add(s) and not add(s)
    f = s.shadow_all_follows(False)[0]
    assert f["symbol"] == "BABA" and f["source"] == "callout:buddybear" and f["size_label"] == "Large" and f["size_ordinal"] == 3
    assert f["entry_ask"] == 3.5 and f["entry_bid"] is None and f["entry_price_is_posted"] is True and f["dte"] == 35
    assert "days_to_earnings" in f["missing_features"] and "entry_bid" in f["missing_features"]
    assert s.shadow_all_follows(True) == []


@pytest.mark.parametrize("bad", [dict(size="Huge"), dict(right="X"), dict(price=0), dict(strike=-1), dict(expiry=DAY), dict(symbol="BA BA"), dict(source="a b")])
def test_record_rejects_bad_input(bad):
    with pytest.raises(ValueError):
        add(Store(":memory:"), **bad)


def test_callouts_stay_out_of_the_generic_gate_and_independent_sample():
    s = Store(":memory:")
    add(s)
    add(s, symbol="NBIS", strike=150, price=3.9, size="Medium")
    rep = shadow.report(s, False, DAY)
    assert rep["callouts_logged"] == 2 and rep["followed"] == 0 and rep["independent_observations"] == 0 and rep["underlyings"] == 0


def test_open_symbols_lists_names_so_scanner_reads_them():
    s = Store(":memory:")
    add(s)
    assert callouts.open_symbols(s, DAY) == ["BABA"]
    assert callouts.open_symbols(s, DAY, True) == []
    assert callouts.open_symbols(s, EXP + timedelta(days=1)) == []  # expired


def test_scan_extends_callout_path_and_summary_reports_return_without_a_verdict():
    s = Store(":memory:")
    add(s)
    now = datetime(2026, 11, 20, 15, tzinfo=timezone.utc)
    row = ChainRow(OptionContract("BABA", EXP, Right.CALL, 90.0), 4.2, 4.4, 800, 500, 0.5)
    snap = MarketSnapshot("BABA", 88.0, (85.0, 86.0, 88.0), (row,), now, "t", True, False)
    assert shadow.observe(s, snap, date(2026, 11, 20), now, False)["points"] == 1
    out = callouts.summary(s, False, date(2026, 11, 20))
    assert out["count"] == 1 and out["callouts"][0]["return_to_latest_bid"] == 0.2 and out["inference_allowed"] is False
    assert out["by_size"] == {"Large": 1}


def test_api_summary_and_fictional_guard():
    from optplat.api import create_app
    from optplat.broker import SimBroker
    from optplat.engine import EngineConfig, TradingEngine
    from optplat.marketdata import DemoDataProvider
    from optplat.orders import OrderManager
    from optplat.strategy import LiquidTrendStrategy

    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    h = {"X-API-Token": "t" * 24}
    body = {"symbol": "BABA", "expiry": "2026-12-24", "strike": 90, "price": 3.5, "size": "Large", "source": "buddybear", "day": "2026-11-19"}
    with TestClient(create_app(manager, "t" * 24, engine, None)) as c:
        assert c.get("/api/callouts").status_code == 401 and c.post("/api/callouts", json=body).status_code == 401
        assert c.get("/api/callouts", headers=h).json()["count"] == 0
        assert c.post("/api/callouts", json=body, headers=h).status_code == 409  # demo provider is fictional


def test_cli_logs_and_rejects(tmp_path, capsys):
    db = str(tmp_path / "t.db")
    base = ["--db", db, "--symbol", "NBIS", "--expiry", "2026-12-24", "--strike", "150", "--price", "3.9", "--source", "buddybear", "--day", "2026-11-19"]
    assert callouts.main(base + ["--size", "Medium"]) == 0 and "logged" in capsys.readouterr().out
    assert callouts.main(base + ["--size", "Huge"]) == 2
