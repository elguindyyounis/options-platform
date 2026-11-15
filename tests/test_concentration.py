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


def test_liquidity_split_separates_oversized_unknown_and_realistic_trades():
    from optplat.concentration import is_oversized, liquidity_split

    assert is_oversized(None, None) is None            # unknown is never assumed fine
    assert is_oversized(10.0, None) is False and is_oversized(10.1, None) is True
    assert is_oversized(None, 5.0) is False and is_oversized(1.0, 5.1) is True
    s = liquidity_split([(500.0, 35.0, None), (-20.0, 2.0, 1.0), (-30.0, None, None), (None, 50.0, 9.0)])
    assert s["closed"] == 3 and (s["oversized_trades"], s["within_limits_trades"], s["unknown_trades"]) == (1, 1, 1)
    assert (s["oversized_pnl"], s["within_limits_pnl"], s["unknown_pnl"]) == (500.0, -20.0, -30.0)
    assert s["positive_only_if_oversized"] is True


def test_liquidity_split_is_not_flagged_when_realistic_trades_also_win_or_when_empty():
    from optplat.concentration import liquidity_split

    ok = liquidity_split([(500.0, 35.0, None), (40.0, 2.0, 1.0)])
    assert ok["positive_only_if_oversized"] is False
    empty = liquidity_split([])
    assert empty["closed"] == 0 and empty["oversized_pnl"] is None and empty["positive_only_if_oversized"] is False
    assert liquidity_split([(-5.0, 90.0, None)])["positive_only_if_oversized"] is False   # a loss is not flattered


def test_the_post_mortem_tag_and_the_split_use_the_same_cutoffs():
    from optplat.concentration import OVERSIZE_OI_PCT, OVERSIZE_VOLUME_PCT

    assert (OVERSIZE_VOLUME_PCT, OVERSIZE_OI_PCT) == (10.0, 5.0)   # unchanged from the original tag
