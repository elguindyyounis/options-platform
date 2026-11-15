import pytest

from optplat.stats import MIN_TRADES_FOR_EVIDENCE, summarize_closed, wilson_interval


def row(entry, exit_, qty=1):
    return {"entry": entry, "exit": exit_, "pnl": (exit_ - entry) * qty * 100}


def test_empty_sample_returns_nulls_not_zeros():
    s = summarize_closed([])
    assert s["sample_label"] == "SAMPLE_TOO_SMALL"
    assert s["profit_factor"] is None and s["win_rate_ci95_pct"] is None
    assert s["max_closed_drawdown_usd"] is None and s["avg_trade_return_pct"] is None


def test_single_win_is_flagged_and_interval_is_wide():
    s = summarize_closed([row(1.0, 2.0)])
    assert s["sample_label"] == "SAMPLE_TOO_SMALL"
    lo, hi = s["win_rate_ci95_pct"]
    assert lo < 25 and hi == 100.0  # one win does not mean a 100% win rate
    assert s["profit_factor"] is None  # no losses: undefined, not infinite


def test_profit_factor_drawdown_and_concentration():
    s = summarize_closed([row(1, 2), row(1, 0.5), row(1, 0.4), row(1, 1.5)])
    assert s["profit_factor"] == pytest.approx(150 / 110, abs=1e-3)
    assert s["max_closed_drawdown_usd"] == 110.0  # +100, -50, -60 -> peak 100, trough -10
    assert s["best_trade_share_of_gross_wins_pct"] == pytest.approx(66.7, abs=0.1)
    assert s["avg_trade_return_pct"] == pytest.approx((100 - 50 - 60 + 50) / 4, abs=0.01)


def test_minimum_sample_label_switches_at_threshold():
    rows = [row(1, 1.1)] * MIN_TRADES_FOR_EVIDENCE
    assert summarize_closed(rows[:-1])["sample_label"] == "SAMPLE_TOO_SMALL"
    s = summarize_closed(rows)
    assert s["sample_label"] == "MINIMUM_SAMPLE_MET" and "no edge" in s["limitations"]


def test_wilson_interval_bounds():
    assert wilson_interval(0, 0) is None
    lo, hi = wilson_interval(15, 30)
    assert 0 <= lo < 50 < hi <= 100
    assert wilson_interval(0, 5)[0] == 0.0
