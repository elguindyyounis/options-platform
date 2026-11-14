from optplat.stats import MIN_TRADES_FOR_READING, sample_assessment, wilson_interval_pct


def test_wilson_known_values():
    assert wilson_interval_pct(0, 0) is None
    assert wilson_interval_pct(5, 4) is None
    lo, hi = wilson_interval_pct(1, 1)
    assert lo < 25 and hi == 100.0          # one win proves almost nothing
    lo, hi = wilson_interval_pct(50, 100)
    assert 40 < lo < 41 and 59 < hi < 60    # textbook ~[40.4, 59.6]


def test_small_samples_are_labelled_insufficient():
    a = sample_assessment([10.0] * 3)
    assert a["status"] == "INSUFFICIENT_SAMPLE" and a["closed_trades"] == 3
    assert sample_assessment([])["status"] == "NO_TRADES"
    assert sample_assessment([1.0] * MIN_TRADES_FOR_READING)["status"] == "DESCRIPTIVE_ONLY"


def test_pnl_without_best_trade_exposes_one_lucky_win():
    a = sample_assessment([500.0, -20.0, -30.0])
    assert a["realized_pnl_without_best_trade"] == -50.0
