import json
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import optplat.signals as signals
from helpers import NOW
from optplat.marketdata import ChainRow, snapshot_to_dict
from optplat.models import OptionContract, Right
from optplat.signals import (SIGNAL_NAMES, SignalNotValidated, VALIDATED_SIGNALS, activity, bs_gamma, compute_signals,
                             coverage, gex, liquidity, liquidity_tier, main, spearman, study_signal, use_signal)
from optplat.store import Store
from test_engine import EXPIRY, UP, snapshot


def cr(strike, right=Right.CALL, bid=4.9, ask=5.1, vol=200, oi=2000, iv=0.3, expiry=EXPIRY):
    return ChainRow(OptionContract("AAA", expiry, right, float(strike)), bid, ask, vol, oi, iv)


def snap(*rows, underlying=UP[-1]):
    return replace(snapshot(), rows=tuple(rows), underlying=underlying)


# ------------------------------------------------------------ gate: nothing is usable until validated
def test_no_signal_is_validated_by_default_and_use_signal_refuses():
    assert VALIDATED_SIGNALS == frozenset()
    for name in SIGNAL_NAMES:
        with pytest.raises(SignalNotValidated):
            use_signal(name)
    with pytest.raises(KeyError):
        use_signal("magic")


def test_a_signal_can_be_used_only_after_the_owner_adds_it(monkeypatch):
    monkeypatch.setattr(signals, "VALIDATED_SIGNALS", frozenset({"gex_total"}))
    use_signal("gex_total")
    with pytest.raises(SignalNotValidated):
        use_signal("unusual_count")


def test_every_result_is_labelled_unvalidated():
    out = compute_signals(snap(cr(160)), NOW)
    assert out["status"] == "UNVALIDATED" and "None is validated" in out["caveat"]


# ------------------------------------------------------------ gamma and GEX
def test_black_scholes_gamma_matches_the_textbook_value_and_rejects_bad_input():
    assert bs_gamma(100, 100, 1, 0.2, 0.0) == pytest.approx(0.0198476, rel=1e-4)
    for bad in ((0, 100, 1, 0.2), (100, 100, 0, 0.2), (100, 100, 1, -0.1), (math.nan, 100, 1, 0.2), (100, 100, 1, math.inf)):
        assert bs_gamma(*bad) is None


def test_calls_add_exposure_and_puts_subtract_it():
    calls = gex(snap(cr(160, Right.CALL)), NOW)["total_usd_per_1pct"]
    puts = gex(snap(cr(160, Right.PUT)), NOW)["total_usd_per_1pct"]
    assert calls > 0 and puts == -calls
    assert gex(snap(cr(160, Right.CALL), cr(160, Right.PUT)), NOW)["total_usd_per_1pct"] == 0


def test_rows_that_cannot_be_modelled_are_skipped_and_counted_not_guessed():
    out = gex(snap(cr(160), cr(165, iv=None), cr(170, oi=0), cr(175, oi=None), cr(180, expiry=NOW.date())), NOW)
    assert out["rows_used"] == 1 and out["rows_skipped"] == 4


def test_gex_is_always_marked_partial_and_states_its_assumptions():
    out = gex(snap(cr(160)), NOW)
    assert out["partial_chain"] is True and any("contested" in a for a in out["assumptions"])


def test_gex_says_when_an_expiry_has_only_one_side_so_the_net_is_not_readable():
    one = gex(snap(cr(160, Right.CALL), cr(165, Right.CALL)), NOW)
    assert one["coverage_label"] == "ONE_SIDED_EXPIRIES" and one["net_is_interpretable"] is False
    assert one["one_sided_expiries"] == [EXPIRY.isoformat()] and one["expiries_used"] == 1
    both = gex(snap(cr(160, Right.CALL), cr(160, Right.PUT)), NOW)
    assert both["coverage_label"] == "BOTH_SIDES_EVERY_EXPIRY" and both["net_is_interpretable"] is True
    assert both["one_sided_expiries"] == []


def test_gex_one_side_per_expiry_is_judged_per_expiry_not_across_the_chain():
    later = EXPIRY + timedelta(days=7)
    out = gex(snap(cr(160, Right.CALL), cr(160, Right.PUT), cr(160, Right.CALL, expiry=later)), NOW)
    assert out["net_is_interpretable"] is False and out["one_sided_expiries"] == [later.isoformat()]


def test_gex_with_no_usable_rows_is_not_interpretable():
    out = gex(snap(cr(160, iv=None)), NOW)
    assert out["coverage_label"] == "NO_ROWS_USED" and out["net_is_interpretable"] is False


def test_the_gamma_flip_strike_is_where_cumulative_exposure_changes_sign():
    # puts below spot dominate at low strikes (negative), calls above dominate at higher strikes (positive)
    rows = [cr(150, Right.PUT, oi=5000), cr(155, Right.PUT, oi=3000), cr(160, Right.CALL, oi=4000), cr(170, Right.CALL, oi=9000)]
    out = gex(snap(*rows, underlying=159.0), NOW)
    assert out["flip_strike"] in (160.0, 170.0) and gex(snap(cr(160)), NOW)["flip_strike"] is None


# ------------------------------------------------------------ activity, liquidity, coverage
def test_unusual_activity_needs_volume_at_least_equal_to_open_interest_and_enough_of_both():
    rows = [cr(160, vol=600, oi=400), cr(165, vol=300, oi=1000), cr(170, vol=90, oi=60), cr(175, vol=500, oi=10),
            cr(180, Right.PUT, vol=1200, oi=800)]
    out = activity(snap(*rows))
    assert [u["volume_to_oi"] for u in out["unusual"]] == [1.5, 1.5]  # 600/400 and 1200/800
    assert out["unusual_count"] == 2
    assert out["unusual"][0]["premium_usd"] == 300_000  # the call: mid 5.00 x 600 contracts x 100 shares
    assert "direction is unknown" in out["note"]


def test_call_put_ratios_are_undefined_not_infinite_when_one_side_is_empty():
    out = activity(snap(cr(160, vol=100, oi=1000)))
    assert out["call_put_volume_ratio"] is None and out["call_put_oi_ratio"] is None
    both = activity(snap(cr(160, vol=300, oi=1000), cr(160, Right.PUT, vol=100, oi=500)))
    assert both["call_put_volume_ratio"] == 3.0 and both["call_put_oi_ratio"] == 2.0


def test_liquidity_tiers_and_counts():
    assert liquidity_tier(4, 150, 1500) == "A" and liquidity_tier(8, 60, 600) == "B" and liquidity_tier(12, 500, 5000) == "C"
    assert liquidity_tier(4, None, None) == "C"
    tiers = liquidity(snap(cr(160, bid=4.95, ask=5.0), cr(165, bid=4.7, ask=5.0, vol=60, oi=600), cr(170, bid=2.0, ask=5.0)))
    assert tiers == {"A": 1, "B": 1, "C": 1}


def test_coverage_says_how_much_of_the_chain_and_which_fields_were_seen():
    c = coverage(snap(cr(150), cr(170, iv=None), cr(190, vol=None), underlying=160.0))
    assert c["rows"] == 3 and c["expiries"] == 1 and c["strike_range_pct_of_spot"] == [-6.2, 18.8]
    assert c["pct_with_iv"] == pytest.approx(66.7, abs=0.1) and c["pct_with_volume"] == pytest.approx(66.7, abs=0.1)
    assert coverage(replace(snapshot(), rows=()))["rows"] == 0


# ------------------------------------------------------------ studying a signal
def test_spearman_handles_ties_and_degenerate_input():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0 and spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert spearman([1, 1, 1], [1, 2, 3]) is None and spearman([1, 2], [1, 2]) is None
    assert spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(0.949, abs=0.001)


def put_snapshots(store, ratios, spot_moves, start=NOW, step_hours=24):
    """One snapshot per day. Day i has a call/put volume ratio ratios[i]; the underlying then moves spot_moves[i]%."""
    spot = 100.0
    for i, (ratio, move) in enumerate(zip(ratios, spot_moves + [0.0])):
        at = start + timedelta(hours=step_hours * i)
        rows = (cr(100, Right.CALL, vol=int(1000 * ratio), oi=5000), cr(100, Right.PUT, vol=1000, oi=5000))
        s = replace(snapshot(), underlying=spot, rows=rows, as_of=at, closes=tuple([spot] * 60))
        store.record_snapshot("AAA", at, at, "test", False, True, snapshot_to_dict(s))
        spot *= 1 + move / 100


def test_a_study_finds_a_planted_relationship_but_still_calls_it_descriptive_and_unvalidated():
    store = Store(":memory:")
    put_snapshots(store, [0.5, 1.0, 2.0, 0.8, 1.5, 3.0, 0.6, 1.2], [-1.0, 0.5, 2.0, -0.5, 1.0, 3.0, -0.9])
    out = study_signal(store, "call_put_volume_ratio", horizon_h=24)
    assert out["observations"] == 7 and out["spearman_rho"] == 1.0
    assert out["descriptive_only"] is True and out["status"] == "UNVALIDATED"
    assert "does not validate" in out["caveat"]
    assert VALIDATED_SIGNALS == frozenset()  # a study never validates anything


def test_a_gap_in_the_recording_is_skipped_not_stretched():
    store = Store(":memory:")
    put_snapshots(store, [1.0, 2.0, 3.0], [1.0, 1.0], step_hours=24)
    far = NOW + timedelta(days=10)
    s = replace(snapshot(), underlying=150.0, as_of=far, closes=tuple([100.0] * 60))
    store.record_snapshot("AAA", far, far, "test", False, True, snapshot_to_dict(s))
    out = study_signal(store, "call_put_volume_ratio", horizon_h=24)
    assert out["skipped_gap"] == 1 and out["observations"] == 2  # the day-2 reading has no snapshot near day 3


def test_a_study_on_nothing_reports_no_observations_and_unknown_signals_are_errors():
    out = study_signal(Store(":memory:"), "gex_total")
    assert out["observations"] == 0 and out["spearman_rho"] is None and out["descriptive_only"] is True
    with pytest.raises(KeyError):
        study_signal(Store(":memory:"), "magic")


def test_fictional_snapshots_are_never_studied():
    store = Store(":memory:")
    s = replace(snapshot(), rows=(cr(160), cr(160, Right.PUT)))
    for i in range(3):
        at = NOW + timedelta(days=i)
        store.record_snapshot("AAA", at, at, "demo", True, True, snapshot_to_dict(replace(s, as_of=at)))
    assert study_signal(store, "unusual_count")["observations"] == 0


# ------------------------------------------------------------ CLI and API
def test_cli_scan_and_study_are_read_only(tmp_path, capsys):
    db = tmp_path / "s.db"
    store = Store(str(db))
    put_snapshots(store, [1.0, 2.0, 3.0, 1.5], [1.0, 2.0, 0.5])
    before = db.read_bytes()
    assert main(["--db", str(db), "scan"]) == 0
    assert "UNVALIDATED" in capsys.readouterr().out
    assert main(["--db", str(db), "study", "unusual_count"]) == 0
    assert json.loads(capsys.readouterr().out)["signal"] == "unusual_count"
    assert db.read_bytes() == before
    assert main(["--db", str(tmp_path / "missing.db"), "scan"]) == 1


def test_api_signals_endpoint_needs_the_token_and_404s_without_data():
    from optplat.api import create_app
    from optplat.broker import SimBroker
    from optplat.engine import TradingEngine
    from optplat.marketdata import StaticDataProvider
    from optplat.orders import OrderManager
    from optplat.strategy import LiquidTrendStrategy
    from test_api_engine import H, TOKEN

    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, StaticDataProvider(), LiquidTrendStrategy())
    with TestClient(create_app(manager, TOKEN, engine)) as c:
        assert c.get("/api/signals/AAA").status_code == 401
        assert c.get("/api/signals/AAA", headers=H).status_code == 404
        s = replace(snapshot(), rows=(cr(160), cr(160, Right.PUT)), as_of=NOW)
        manager.store.record_snapshot("AAA", NOW, NOW, "t", False, True, snapshot_to_dict(s))
        body = c.get("/api/signals/aaa", headers=H).json()
        assert body["status"] == "UNVALIDATED" and body["gex"]["partial_chain"] is True
