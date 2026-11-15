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


def test_group_story_flags_a_total_carried_by_one_underlying():
    from optplat.concentration import group_story
    g = group_story([("SPY", 500.0), ("SPY", 100.0), ("QQQ", -200.0), ("IWM", -150.0), ("AAPL", None)])
    assert g["best_group"] == "SPY" and g["group_count"] == 3 and g["closed"] == 4
    assert g["realized_ex_best_group"] == -350.0 and g["one_group_story"] is True
    assert g["best_group_share_pct"] == 100 * 600 / 250 and g["too_thin"] is False


def test_group_story_broad_result_is_not_flagged_and_unknown_key_is_kept():
    from optplat.concentration import group_story
    g = group_story([("A", 100.0), ("B", 90.0), (None, 80.0), ("", -10.0)])
    assert g["one_group_story"] is False and g["group_count"] == 3
    unknown = next(r for r in g["groups"] if r["group"] == "unknown")
    assert unknown["closed"] == 2 and unknown["pnl"] == 70.0


def test_group_story_empty_and_losing_and_few_groups():
    from optplat.concentration import group_story
    e = group_story([])
    assert e["one_group_story"] is None and e["too_thin"] is True and e["groups"] == []
    assert group_story([("A", -5.0), ("B", -1.0), ("C", -2.0)])["one_group_story"] is False
    assert group_story([("A", 5.0), ("A", 5.0)])["too_thin"] is True


def test_close_day_is_utc_and_tolerates_bad_input():
    from optplat.concentration import close_day
    assert close_day("2026-11-12T23:30:00-05:00") == "2026-11-13"
    assert close_day("2026-11-12T10:00:00Z") == "2026-11-12"
    assert close_day(None) is None and close_day("nonsense") is None


def test_closed_trade_drawdown_follows_close_order_not_input_order():
    from optplat.concentration import closed_trade_drawdown
    d = closed_trade_drawdown([
        ("2026-11-03T15:00:00Z", -30.0), ("2026-11-01T15:00:00Z", 100.0),
        ("2026-11-02T15:00:00Z", -60.0), ("2026-11-04T15:00:00Z", 50.0), ("2026-11-05T15:00:00Z", -10.0),
    ])
    # curve: +100, +40, +10, +60, +50 -> peak 100, trough 10
    assert d["max_drawdown_usd"] == 90.0 and d["ordered"] == 5 and d["unordered"] == 0
    assert d["is_account_drawdown"] is False and d["is_lower_bound"] is True and d["too_thin"] is False


def test_closed_trade_drawdown_counts_a_losing_start_and_never_guesses_unplaceable_trades():
    from optplat.concentration import closed_trade_drawdown
    d = closed_trade_drawdown([("2026-11-01T10:00:00Z", -40.0), (None, -500.0), ("garbage", -500.0), ("2026-11-02T10:00:00Z", None)])
    assert d["max_drawdown_usd"] == 40.0 and d["closed"] == 3 and d["ordered"] == 1 and d["unordered"] == 2
    assert d["too_thin"] is True


def test_closed_trade_drawdown_ties_take_losses_first_and_empty_is_null():
    from optplat.concentration import closed_trade_drawdown
    t = "2026-11-01T10:00:00Z"
    assert closed_trade_drawdown([(t, 50.0), (t, -50.0)])["max_drawdown_usd"] == 50.0
    e = closed_trade_drawdown([])
    assert e["max_drawdown_usd"] is None and e["too_thin"] is True
    assert closed_trade_drawdown([("2026-11-01T10:00:00Z", 5.0)])["max_drawdown_usd"] == 0.0
