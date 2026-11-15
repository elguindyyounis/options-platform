from dataclasses import replace
from datetime import timedelta

from helpers import NOW
from optplat.gex import net_gex
from optplat.marketdata import ChainRow, MarketSnapshot
from optplat.models import OptionContract, Right
from test_engine import UP, build, snapshot

EXP = NOW.date() + timedelta(days=30)


def snap(rows, fictional=False):
    return MarketSnapshot("AAA", 100.0, UP, tuple(rows), NOW, "test", True, fictional)


def row(right, strike=100.0, oi=1000, iv=0.3, expiry=EXP):
    return ChainRow(OptionContract("AAA", expiry, right, strike), 1.0, 1.1, 10, oi, iv)


def test_calls_positive_puts_negative_and_equal_sides_cancel():
    out = net_gex(snap([row(Right.CALL), row(Right.PUT)]))
    assert out["net_gex_musd"] == 0.0 and out["rows_used"] == 2 and out["rows_skipped"] == 0
    only_calls = net_gex(snap([row(Right.CALL)]))
    only_puts = net_gex(snap([row(Right.PUT)]))
    assert only_calls["net_gex_musd"] > 0 > only_puts["net_gex_musd"]
    assert only_calls["largest_positive_strike"] == 100.0 and only_calls["largest_negative_strike"] is None
    assert only_puts["largest_negative_strike"] == 100.0 and only_puts["largest_positive_strike"] is None
    assert only_calls["model"] == "ASSUMED_CALL_PLUS_PUT_MINUS_V1"


def test_missing_or_bad_inputs_are_skipped_and_counted_never_guessed():
    bad = [
        row(Right.CALL, oi=None), row(Right.CALL, iv=None), row(Right.CALL, oi=0),
        row(Right.CALL, iv=0.0), row(Right.CALL, iv=float("nan")),
        row(Right.CALL, expiry=NOW.date() - timedelta(days=1)),
        row(Right.CALL, expiry=NOW.date() + timedelta(days=90)),
    ]
    out = net_gex(snap(bad))
    assert out["net_gex_musd"] is None and out["rows_used"] == 0 and out["rows_skipped"] == len(bad)


def test_fictional_flag_is_carried_and_empty_chain_is_null():
    assert net_gex(snap([row(Right.CALL)], fictional=True))["fictional"] is True
    assert net_gex(snap([]))["net_gex_musd"] is None


def test_cycle_report_includes_gex_without_changing_entries():
    engine, manager, *_ = build(auto_entries=True)
    report = engine.run_cycle()
    assert report["gex"] and report["gex"][0]["symbol"] == "AAA"
    assert report["gex"][0]["net_gex_musd"] is None  # snapshot() fixture's only row expires beyond 45 days
    assert any("NOT observed dealer positioning" in a for a in report["gex_assumptions"])
    assert len(manager.list()) <= len(report["entries"])


def test_dashboard_has_gex_panel_with_text_only_dom():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "src" / "optplat" / "static"
    html, js = (root / "index.html").read_text(), (root / "app.js").read_text()
    assert 'id="gex-table"' in html and "assumption" in html and "renderGex" in js
    assert "innerHTML" not in js
