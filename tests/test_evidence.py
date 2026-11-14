from optplat.evidence import INSUFFICIENT, MIN_TRADES_FOR_RESULT, PRELIMINARY, evidence_summary, wilson_interval


def test_one_win_is_not_a_hundred_percent_result():
    lo, hi = wilson_interval(1, 1)
    assert lo < 25 and hi == 100.0
    s = evidence_summary([120.0])
    assert s["verdict"] == INSUFFICIENT and s["closed_trades"] == 1
    assert any("anecdote" in n for n in s["notes"])


def test_no_trades_has_no_interval_and_is_insufficient():
    s = evidence_summary([])
    assert s["verdict"] == INSUFFICIENT
    assert s["win_rate_ci95_pct"] is None and s["expectancy_per_trade"] is None
    assert wilson_interval(0, 0) is None and wilson_interval(5, 3) is None


def test_enough_trades_is_only_preliminary_and_still_disclaims_edge():
    s = evidence_summary([10.0, -5.0] * (MIN_TRADES_FOR_RESULT // 2))
    assert s["verdict"] == PRELIMINARY
    assert any("not evidence of an edge" in n for n in s["notes"])
    assert s["win_rate_ci95_pct"][0] < 50 < s["win_rate_ci95_pct"][1]


def test_interval_narrows_with_sample_size():
    small = wilson_interval(6, 10)
    big = wilson_interval(600, 1000)
    assert (small[1] - small[0]) > (big[1] - big[0])


def test_one_lucky_trade_is_flagged():
    s = evidence_summary([900.0, 50.0, -40.0])
    assert s["best_trade_share_of_profit_pct"] > 50
    assert any("best single trade" in n for n in s["notes"])


def test_truncation_is_disclosed():
    assert evidence_summary([1.0], truncated=True)["history_truncated"] is True
    assert any("read limit" in n for n in evidence_summary([1.0], truncated=True)["notes"])
