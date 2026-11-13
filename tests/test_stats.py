from optplat.stats import MIN_TRADES_FOR_RESULT, sample_assessment, wilson_interval


def test_wilson_empty_and_invalid():
    assert wilson_interval(0, 0) is None
    assert wilson_interval(5, 3) is None


def test_wilson_small_sample_is_wide():
    lo, hi = wilson_interval(2, 3)
    assert lo < 25 and hi > 90  # 2 of 3 wins says almost nothing


def test_wilson_bounds_and_narrowing():
    lo1, hi1 = wilson_interval(5, 10)
    lo2, hi2 = wilson_interval(500, 1000)
    assert 0 <= lo1 < 50 < hi1 <= 100
    assert (hi2 - lo2) < (hi1 - lo1)
    assert wilson_interval(0, 5)[0] == 0.0 and wilson_interval(5, 5)[1] == 100.0


def test_assessment_empty_is_insufficient():
    a = sample_assessment([])
    assert a["sample_status"] == "INSUFFICIENT" and a["win_rate_ci95_pct"] is None
    assert a["avg_win"] is None and a["best_trade"] is None


def test_assessment_few_trades_insufficient_with_payoff():
    a = sample_assessment([100.0, -40.0, -60.0])
    assert a["sample_status"] == "INSUFFICIENT"
    assert a["avg_win"] == 100.0 and a["avg_loss"] == -50.0
    assert a["best_trade"] == 100.0 and a["worst_trade"] == -60.0


def test_assessment_never_claims_more_than_preliminary():
    a = sample_assessment([10.0] * MIN_TRADES_FOR_RESULT)
    assert a["sample_status"] == "PRELIMINARY"
    assert "paper" in a["sample_note"]
