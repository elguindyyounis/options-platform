from optplat.evidence import MIN_TRADES_FOR_READING, sample_status, trade_evidence, wilson_interval_pct


def _t(entry, exit_, qty=1):
    return {"entry": entry, "exit": exit_, "pnl": (exit_ - entry) * qty * 100}


def test_wilson_interval_known_values():
    assert wilson_interval_pct(0, 0) is None
    assert wilson_interval_pct(5, 4) is None
    lo, hi = wilson_interval_pct(1, 1)
    assert lo < 25 and hi == 100.0          # one win proves almost nothing
    lo, hi = wilson_interval_pct(50, 100)
    assert (lo, hi) == (40.4, 59.6)


def test_small_samples_are_labelled_insufficient():
    assert sample_status(0) == "NO_TRADES"
    assert sample_status(MIN_TRADES_FOR_READING - 1) == "INSUFFICIENT"
    assert sample_status(MIN_TRADES_FOR_READING) == "MINIMUM_MET"


def test_trade_evidence_summarises_concentration_and_tails():
    ev = trade_evidence([_t(1.0, 2.0), _t(1.0, 0.7), _t(2.0, 2.2)])
    assert ev["sample_status"] == "INSUFFICIENT"
    assert ev["worst_return_pct"] == -30.0 and ev["best_return_pct"] == 100.0
    assert ev["median_return_pct"] == 10.0
    assert ev["largest_win_share_of_gross_profit_pct"] == round(100 / 120 * 100, 1)
    assert ev["win_rate_ci95_pct"][1] < 100


def test_trade_evidence_empty_and_all_losses():
    ev = trade_evidence([])
    assert ev["sample_status"] == "NO_TRADES" and ev["win_rate_ci95_pct"] is None
    ev = trade_evidence([_t(1.0, 0.5)])
    assert ev["largest_win_share_of_gross_profit_pct"] is None
