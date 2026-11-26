"""Day-clustered intervals and subperiod stability beside registered pass rules (synthetic numbers only)."""
from optplat import robustness as rb
from test_lane_hypotheses import lh, st1_trades


def _days(n):
    return [f"2026-12-{d:02d}" for d in range(1, n + 1)]


def test_one_big_day_passes_an_observation_level_interval_but_not_a_day_level_one():
    # 9 flat-to-slightly-negative days with 2 observations each, then 1 day with 20 big winners that move together.
    rows = [(d, -0.1) for d in _days(9) for _ in range(2)] + [("2026-12-10", 3.0)] * 20
    lo, _ = lh._bootstrap_ci([v for _, v in rows], 0.05)
    assert lo > 0  # what the observation-level interval says
    out = rb.check(rows, rows, passed=True)
    assert out["ci_day_clustered"][0] <= 0
    assert "whole days includes zero" in out["warning"]


def test_an_edge_that_lives_in_one_block_of_days_is_flagged():
    rows = [(d, 2.0 if i < 4 else -0.05) for i, d in enumerate(_days(12)) for _ in range(3)]
    out = rb.check(rows[-12:], rows, passed=True)
    assert out["subperiod_means"][0] > 0 and out["subperiod_means"][1] < 0 and out["subperiod_means"][2] < 0
    assert "consecutive blocks" in out["warning"]


def test_a_steady_result_carries_no_warning_and_a_failure_never_does():
    rows = [(d, 0.5 + 0.1 * (i % 3)) for i, d in enumerate(_days(20)) for _ in range(3)]
    assert rb.check(rows, rows, passed=True)["warning"] is None
    bad = [(d, -1.0) for d in _days(5)]
    assert rb.check(bad, bad, passed=False)["warning"] is None


def test_two_group_difference_resamples_days_for_both_groups_together():
    t = [(d, 1.0) for d in _days(10)]
    c = [(d, 0.0) for d in _days(10)]
    lo, hi = rb.day_clustered_ci(t, baseline=c)
    assert lo == hi == 1.0
    assert rb.subperiod_means(t, baseline=c) == [1.0, 1.0, 1.0]
    assert rb.day_clustered_ci([("2026-12-01", 1.0)]) is None and rb.subperiod_means(t[:2]) is None


def test_lane_verdicts_carry_the_checks_without_changing_the_verdict():
    r = lh.evaluate(lh.ST1, st1_trades(lambda i, j: 0.5 + 0.1 * ((i + j) % 3)))
    assert r["verdict"] == "PASSED_CRITERIA"
    assert r["robustness"]["warning"] is None and r["robustness"]["ci_day_clustered"][0] > 0
    assert len(r["robustness"]["subperiod_means"]) == 3
