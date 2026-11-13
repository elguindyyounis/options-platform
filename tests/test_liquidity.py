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


def _lane_with(store, rows):
    """rows: (entry, exit, postmortem or None). Fictional option-lane trades, one contract each, qty 2, multiplier 100."""
    from optplat.shortterm import lane_report
    t0 = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
    for i, (entry, exit_, pm) in enumerate(rows):
        tid = store.lane_open("x-lane", "SPY", t0, entry, 2, True, {"multiplier": 100, "fees_open": 0.0})
        store.lane_close(tid, t0 + timedelta(hours=1), exit_, "target", {"fees_close": 0.0, **({"postmortem": pm} if pm is not None else {})})
    return lane_report(store, "x-lane", True, t0, rules=[], limitations=[], symbols=["SPY"], exit_text={})


def test_lane_summary_shows_stressed_pnl_beside_bid_pnl_over_the_same_trades():
    from optplat.store import Store
    r = _lane_with(Store(":memory:"), [(1.0, 1.5, {"stress_net": 40.0}), (1.0, 0.5, {"stress_net": -80.0}), (1.0, 2.0, None)])
    s = r["summary"]
    assert s["realized_pnl"] == 200.0  # (100 - 100 + 200) over all three closed trades, qty 2
    assert (s["stressed_trades"], s["stressed_missing"]) == (2, 1)
    assert s["stressed_realized_pnl"] == -40.0 and s["bid_realized_pnl_same_trades"] == 0.0  # (100 - 100) the missing trade is in neither


def test_lane_stressed_pnl_is_none_when_no_trade_has_a_usable_figure():
    from optplat.store import Store
    r = _lane_with(Store(":memory:"), [(1.0, 1.5, None), (1.0, 1.5, {"stress_net": "bad"}), (1.0, 1.5, {"stress_net": float("nan")}), (1.0, 1.5, {"stress_net": True})])
    s = r["summary"]
    assert s["stressed_realized_pnl"] is None and s["bid_realized_pnl_same_trades"] is None and s["stressed_missing"] == 4


def test_post_mortem_stores_the_stressed_dollar_result():
    pm = post_mortem(trade(), 2.0, "target", closed_at(2), {"fees_close": 0.0})
    assert isinstance(pm["stress_net"], float) and pm["stress_net"] <= (2.0 - trade()["entry_price"]) * trade()["quantity"] * 100
