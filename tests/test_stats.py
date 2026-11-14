import pytest

from optplat.stats import MIN_TRADES_FOR_RESULT, sample_quality, wilson_interval


def test_wilson_none_without_trades_or_bad_input():
    assert wilson_interval(0, 0) is None
    assert wilson_interval(5, 3) is None
    assert wilson_interval(-1, 3) is None


def test_wilson_one_win_of_one_is_wide():
    lo, hi = wilson_interval(1, 1)
    assert lo < 25 and hi == 100.0  # a 100% win rate on one trade says almost nothing


def test_wilson_narrows_with_more_trades():
    lo1, hi1 = wilson_interval(5, 10)
    lo2, hi2 = wilson_interval(50, 100)
    assert (hi2 - lo2) < (hi1 - lo1)
    assert lo2 < 50 < hi2


def test_no_trades():
    q = sample_quality([])
    assert q["status"] == "NO_TRADES" and q["win_rate_ci95_pct"] is None
    assert q["realized_pnl_without_best_trade"] is None


def test_small_sample_is_insufficient_and_best_trade_removed():
    q = sample_quality([500.0, -50.0, -40.0])
    assert q["status"] == "INSUFFICIENT"
    assert q["realized_pnl_without_best_trade"] == pytest.approx(-90.0)  # total looked positive
    assert q["best_trade_pnl"] == 500.0 and q["worst_trade_pnl"] == -50.0
    assert "Not a result" in q["note"]


def test_minimum_met_still_carries_caveat():
    q = sample_quality([1.0] * MIN_TRADES_FOR_RESULT)
    assert q["status"] == "MINIMUM_MET"
    assert "necessary but not sufficient" in q["note"]
