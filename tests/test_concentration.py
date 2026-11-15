from optplat.concentration import MIN_TRADES, one_trade_story


def test_no_closed_trades_gives_unknowns_not_zeros():
    r = one_trade_story([])
    assert r["realized_ex_best"] is None and r["one_trade_story"] is None and r["too_thin"] is True


def test_missing_pnl_is_ignored_not_counted_as_zero():
    r = one_trade_story([None, 10.0, None])
    assert r["closed"] == 1 and r["best_pnl"] == 10.0


def test_a_total_that_comes_from_one_trade_is_flagged():
    r = one_trade_story([500.0, -50.0, -40.0, -30.0, 20.0])
    assert r["realized_ex_best"] == -100.0
    assert r["one_trade_story"] is True
    assert r["best_share_pct"] == round(500 / 400 * 100, 1)


def test_a_broad_result_is_not_flagged():
    r = one_trade_story([30.0, 25.0, 20.0, 15.0, -10.0])
    assert r["one_trade_story"] is False and r["realized_ex_best"] == 50.0


def test_a_losing_total_is_never_a_winning_one_trade_story():
    r = one_trade_story([100.0, -300.0])
    assert r["one_trade_story"] is False and r["best_share_pct"] is None


def test_small_samples_are_marked_too_thin():
    assert one_trade_story([1.0] * (MIN_TRADES - 1))["too_thin"] is True
    assert one_trade_story([1.0] * MIN_TRADES)["too_thin"] is False
