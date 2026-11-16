from datetime import datetime, timedelta, timezone

from optplat.liquidity import MAX_CONCESSION_PCT, exit_concession_pct, liquidity_tier, stress_exit
from optplat.postmortem import CAUSES, post_mortem
from test_optionlanes import closed_at, trade


def test_tiers_follow_volume_open_interest_and_spread_and_unknown_is_thin():
    assert liquidity_tier(500, 2000, 4.0) == "PREFERRED"
    assert liquidity_tier(50, 200, 15.0) == "WATCH"
    assert liquidity_tier(5, 2000, 4.0) == "THIN"
    assert liquidity_tier(500, 2000, 25.0) == "THIN"
    assert liquidity_tier(None, 2000, 4.0) == "THIN" and liquidity_tier(500, None, 4.0) == "THIN" and liquidity_tier(500, 2000, None) == "THIN"


def test_concession_grows_with_spread_and_size_and_missing_data_costs_the_maximum():
    tight = exit_concession_pct(1, 1000, 5000, 5.0)
    wide = exit_concession_pct(1, 1000, 5000, 35.0)
    big = exit_concession_pct(200, 1000, 5000, 5.0)
    assert 0.5 <= tight < 1.0 and wide > tight and big > tight
    assert exit_concession_pct(1, None, 5000, 5.0) == MAX_CONCESSION_PCT
    assert exit_concession_pct(1, 100, 100, None) == MAX_CONCESSION_PCT
    assert exit_concession_pct(10_000, 1, 1, 90.0) <= MAX_CONCESSION_PCT


def test_stress_exit_price_is_never_above_the_bid_or_negative():
    for bid in (0.0, 0.05, 3.0):
        s = stress_exit(bid, 5, 20, 100, 30.0)
        assert 0.0 <= s["price"] <= bid


def test_a_win_that_only_exists_at_the_bid_is_tagged_and_a_liquid_win_is_not():
    thin = trade(entry=5.0, qty=20, spread=30.0, oi=60, volume=15)
    pm = post_mortem(thin, 5.4, "target", closed_at(2), {"underlying": 101.0, "fees_close": 1.3, "spread_pct": 30.0})
    assert pm["net_pct"] > 0 and pm["stress_net_pct"] < pm["net_pct"] and "EXIT_STRESS_FLIPS_RESULT" in pm["tags"]
    assert pm["liquidity_tier"] == "THIN"
    liquid = trade(entry=5.0, qty=2, spread=3.0, oi=5000, volume=2000)
    ok = post_mortem(liquid, 7.0, "target", closed_at(2), {"underlying": 101.0, "fees_close": 1.3, "spread_pct": 3.0})
    assert "EXIT_STRESS_FLIPS_RESULT" not in ok["tags"] and ok["liquidity_tier"] == "PREFERRED" and ok["stress_net_pct"] > 0


def test_losses_are_never_tagged_as_flipped_and_missing_volume_is_stressed_hard():
    pm = post_mortem(trade(entry=5.0), 3.0, "stop", closed_at(1), {"underlying": 98.0, "fees_close": 1.3, "spread_pct": 4.0})
    assert "EXIT_STRESS_FLIPS_RESULT" not in pm["tags"]
    no_vol = post_mortem(trade(entry=5.0), 5.3, "target", closed_at(1), {"underlying": 101.0, "fees_close": 1.3, "spread_pct": 4.0})
    assert no_vol["stress_concession_pct"] == MAX_CONCESSION_PCT and no_vol["liquidity_tier"] == "THIN"


def test_the_new_cause_has_a_lesson_and_a_next_step():
    assert "EXIT_STRESS_FLIPS_RESULT" in CAUSES and all(CAUSES["EXIT_STRESS_FLIPS_RESULT"])
