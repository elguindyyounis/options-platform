import math

from optplat.evidence import MIN_TRADES_FOR_ANY_READING, summarize_evidence, wilson_interval


def test_wilson_one_of_one_is_not_certain():
    lo, hi = wilson_interval(1, 1)
    assert lo < 50 and hi == 100.0


def test_wilson_none_without_trades_or_bad_input():
    assert wilson_interval(0, 0) is None
    assert wilson_interval(5, 3) is None


def test_wilson_known_value():
    lo, hi = wilson_interval(50, 100)
    assert (lo, hi) == (40.4, 59.6)


def test_empty_is_insufficient():
    s = summarize_evidence([])
    assert s["verdict"] == "INSUFFICIENT_SAMPLE" and s["win_rate_95ci_pct"] is None


def test_small_sample_always_insufficient_even_if_all_wins():
    s = summarize_evidence([100.0] * (MIN_TRADES_FOR_ANY_READING - 1))
    assert s["verdict"] == "INSUFFICIENT_SAMPLE"


def test_large_sample_still_makes_no_edge_claim():
    s = summarize_evidence([10.0, -5.0] * 30)
    assert s["verdict"] == "NO_CLAIM_PAPER_ONLY"
    assert "edge" in s["note"]


def test_depends_on_one_trade():
    s = summarize_evidence([500.0] + [-10.0] * 40)
    assert s["verdict"] == "DEPENDS_ON_ONE_TRADE"
    assert s["net_pnl_without_best_trade"] == -400.0


def test_non_finite_and_truncation_downgrade():
    pnls = [10.0, -5.0] * 20 + [math.nan]
    assert summarize_evidence(pnls)["verdict"] == "INCOMPLETE_DATA"
    assert summarize_evidence(pnls[:-1], truncated=True)["verdict"] == "INCOMPLETE_DATA"
    assert summarize_evidence(pnls)["excluded_non_finite"] == 1
