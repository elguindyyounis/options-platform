from optplat.evidence import (
    ENOUGH_TO_EXAMINE,
    INSUFFICIENT,
    MIN_TRADES_FOR_RESULT,
    evidence_summary,
    wilson_interval,
)


def test_wilson_single_win_is_wide_not_100_percent():
    lo, hi = wilson_interval(1, 1)
    assert lo < 25 and hi == 100.0


def test_wilson_known_value():
    lo, hi = wilson_interval(50, 100)
    assert 40.0 <= lo <= 40.5 and 59.5 <= hi <= 60.0


def test_wilson_invalid_inputs_fail_closed():
    assert wilson_interval(0, 0) is None
    assert wilson_interval(5, 3) is None
    assert wilson_interval(-1, 3) is None


def test_small_sample_is_insufficient():
    s = evidence_summary([10.0])
    assert s["sample_verdict"] == INSUFFICIENT and "anecdote" in s["evidence_note"]


def test_empty_sample_is_insufficient_without_interval():
    s = evidence_summary([])
    assert s["sample_verdict"] == INSUFFICIENT and s["win_rate_ci95_pct"] is None


def test_threshold_boundary():
    below = evidence_summary([1.0] * (MIN_TRADES_FOR_RESULT - 1))
    at = evidence_summary([1.0] * MIN_TRADES_FOR_RESULT)
    assert below["sample_verdict"] == INSUFFICIENT
    assert at["sample_verdict"] == ENOUGH_TO_EXAMINE
    assert "edge" in at["evidence_note"]
