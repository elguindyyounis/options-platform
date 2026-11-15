from optplat.evaluation import MIN_TRADES_FOR_RESULT, closed_trade_stats, sample_label, wilson_interval


def trade(entry, exit_, at):
    return {"entry": entry, "exit": exit_, "pnl": (exit_ - entry) * 100, "closed_at": at}


def test_wilson_interval_is_wide_for_tiny_samples():
    lo, hi = wilson_interval(2, 2)
    assert lo < 40 and hi == 100.0  # 2/2 wins is not "100%"
    lo, hi = wilson_interval(60, 100)
    assert 50 < lo < 60 < hi < 70


def test_wilson_interval_rejects_nonsense():
    assert wilson_interval(0, 0) is None
    assert wilson_interval(3, 2) is None
    assert wilson_interval(-1, 5) is None


def test_sample_labels_never_say_edge():
    assert sample_label(0) == "NO_CLOSED_TRADES"
    assert sample_label(MIN_TRADES_FOR_RESULT - 1) == "INSUFFICIENT_SAMPLE"
    assert sample_label(MIN_TRADES_FOR_RESULT) == "SAMPLE_ONLY_NOT_AN_EDGE"


def test_stats_empty_is_null_not_zero():
    s = closed_trade_stats([])
    assert s["win_rate_ci95_pct"] is None and s["avg_trade_return_pct"] is None
    assert s["profit_factor"] is None and s["closed_trade_max_drawdown_usd"] is None


def test_stats_values_and_drawdown_order():
    s = closed_trade_stats([trade(1.0, 1.5, "2026-01-03"), trade(1.0, 0.5, "2026-01-01"), trade(1.0, 0.6, "2026-01-02")])
    assert s["trades_used"] == 3 and s["sample_label"] == "INSUFFICIENT_SAMPLE"
    assert s["profit_factor"] == round(50 / 90, 3)
    assert s["closed_trade_max_drawdown_usd"] == 90.0  # sorted by close time: -50, -40, +50
    assert s["avg_trade_return_pct"] == round((-50 - 40 + 50) / 3, 2)


def test_unusable_rows_are_skipped_and_counted():
    rows = [trade(1.0, 2.0, "a"), {"entry": 0, "exit": 1, "pnl": 1, "closed_at": "b"},
            {"entry": 1, "exit": float("nan"), "pnl": float("nan"), "closed_at": "c"}, {"pnl": 1}]
    s = closed_trade_stats(rows)
    assert s["trades_used"] == 1 and s["trades_skipped_unusable"] == 3
