from optplat.evidence import MIN_CLOSED_TRADES, assess_results, wilson_interval


def test_empty_is_insufficient_and_has_no_interval():
    r = assess_results([])
    assert r["status"] == "INSUFFICIENT_SAMPLE" and r["win_rate_interval_pct"] is None
    assert r["pnl_excluding_best_trade"] is None and r["depends_on_best_trade"] is False


def test_single_winner_is_not_a_result_and_interval_is_wide():
    r = assess_results([500.0])
    assert r["status"] == "INSUFFICIENT_SAMPLE"
    lo, hi = r["win_rate_interval_pct"]
    assert lo < 25 and hi == 100.0


def test_depends_on_best_trade_flag():
    assert assess_results([1000.0, -300.0, -400.0, -200.0])["depends_on_best_trade"] is True
    assert assess_results([1000.0, 200.0, -100.0])["depends_on_best_trade"] is False
    assert assess_results([-5.0, -10.0])["depends_on_best_trade"] is False


def test_enough_trades_is_still_labelled_unvalidated():
    r = assess_results([10.0, -5.0] * (MIN_CLOSED_TRADES // 2))
    assert r["status"] == "SUFFICIENT_SAMPLE_UNVALIDATED"
    assert any("does not show an edge" in n for n in r["notes"])


def test_non_finite_values_are_dropped():
    r = assess_results([float("nan"), float("inf"), 5.0])
    assert r["closed_trades"] == 1


def test_wilson_known_value_and_bad_input():
    lo, hi = wilson_interval(5, 10)
    assert (lo, hi) == (23.7, 76.3)
    assert wilson_interval(0, 0) is None and wilson_interval(3, 2) is None


def test_slice_results_labels_each_slice_and_warns_about_slicing():
    from optplat.evidence import slice_results

    rows = [{"underlying": "SPY", "pnl": 100.0}, {"underlying": "SPY", "pnl": -20.0},
            {"underlying": "QQQ", "pnl": 50.0}, {"pnl": -10.0}, {"underlying": "IWM", "pnl": float("nan")}]
    out = slice_results(rows, "underlying")
    assert set(out["slices"]) == {"SPY", "QQQ", "UNKNOWN"}  # NaN-only slice dropped, missing key kept
    assert out["slices"]["SPY"]["closed_trades"] == 2 and out["slices"]["SPY"]["realized_pnl"] == 80.0
    assert all(v["status"] == "INSUFFICIENT_SAMPLE" for v in out["slices"].values())
    assert out["insufficient_slices"] == 3
    assert any("slices from 4 trades" in n for n in out["notes"])


def test_slice_results_single_slice_has_no_multiplicity_warning_and_empty_ok():
    from optplat.evidence import slice_results

    assert slice_results([], "underlying")["slices"] == {}
    one = slice_results([{"underlying": "SPY", "pnl": 1.0}], "underlying")
    assert not any("slices from" in n for n in one["notes"])
