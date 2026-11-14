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


def test_lane_summary_counts_open_trades_with_no_usable_bid_instead_of_silently_zeroing_them():
    import json
    from optplat.shortterm import lane_report
    from optplat.store import Store
    store = Store(":memory:")
    t0 = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
    a = store.lane_open("x-lane", "SPY", t0, 1.0, 2, True, {"multiplier": 100, "fees_open": 0.0})
    store.lane_open("x-lane", "SPY", t0, 1.0, 2, True, {"multiplier": 100, "fees_open": 0.0})  # never marked
    store.set_state(f"lane_mark:{a}", json.dumps({"bid": 1.5, "ask": 1.6, "at": t0.isoformat()}))
    s = lane_report(store, "x-lane", True, t0, rules=[], limitations=[], symbols=["SPY"], exit_text={})["summary"]
    assert s["unrealized_pnl"] == 100.0  # only the marked trade counts
    assert s["unobservable_open"] == 1 and s["unrealized_complete"] is False


def test_lane_summary_is_complete_with_no_open_trades():
    from optplat.store import Store
    s = _lane_with(Store(":memory:"), [(1.0, 1.5, None)])["summary"]
    assert s["unobservable_open"] == 0 and s["unrealized_complete"] is True


def test_dashboard_shows_the_stressed_exit_and_the_left_out_open_trades():
    import pathlib
    js = (pathlib.Path(__file__).parents[1] / "src/optplat/static/app.js").read_text()
    assert "stressed_realized_pnl" in js and "bid_realized_pnl_same_trades" in js and "unobservable_open" in js
    assert "innerHTML" not in js


def _participation_lane(rows, open_rows=()):
    """rows: (entry, exit, why-entered extras). One contract of qty 2, multiplier 100, no fees."""
    from optplat.shortterm import lane_report
    from optplat.store import Store
    store = Store(":memory:")
    t0 = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
    for entry, exit_, extra in rows:
        tid = store.lane_open("x-lane", "SPY", t0, entry, 2, True, {"multiplier": 100, "fees_open": 0.0, **extra})
        store.lane_close(tid, t0 + timedelta(hours=1), exit_, "target", {"fees_close": 0.0})
    for extra in open_rows:
        store.lane_open("x-lane", "SPY", t0, 1.0, 2, True, {"multiplier": 100, "fees_open": 0.0, **extra})
    return lane_report(store, "x-lane", True, t0, rules=[], limitations=[], symbols=["SPY"], exit_text={})["summary"]


def test_participation_splits_closed_pnl_by_size_against_volume_and_open_interest_and_unknown_counts_as_outside():
    ok = {"size_vs_volume_pct": 10.0, "size_vs_oi_pct": 10.0}      # exactly at the yardstick is within
    big_oi = {"size_vs_volume_pct": 1.0, "size_vs_oi_pct": 10.1}
    big_vol = {"size_vs_volume_pct": 10.1, "size_vs_oi_pct": 1.0}
    s = _participation_lane([(1.0, 1.5, ok), (1.0, 2.0, big_oi), (1.0, 0.5, big_vol), (1.0, 3.0, {}), (1.0, 3.0, {"size_vs_volume_pct": None, "size_vs_oi_pct": 1.0})])["participation"]
    assert (s["closed_checked"], s["within_cap"], s["over_cap"], s["unknown"]) == (5, 1, 2, 2)
    assert s["within_cap_realized_pnl"] == 100.0
    assert s["outside_cap_realized_pnl"] == 200.0 + (-100.0) + 400.0 + 400.0  # the lucky oversized and unknown-size wins are kept apart
    assert (s["cap_volume_pct"], s["cap_oi_pct"]) == (10.0, 10.0)


def test_participation_rejects_non_finite_and_boolean_shares_as_unknown():
    bad = {"size_vs_volume_pct": float("nan"), "size_vs_oi_pct": 1.0}
    flag = {"size_vs_volume_pct": True, "size_vs_oi_pct": True}
    s = _participation_lane([(1.0, 1.5, bad), (1.0, 1.5, flag)])["participation"]
    assert (s["within_cap"], s["unknown"], s["within_cap_realized_pnl"]) == (0, 2, None)


def test_participation_counts_open_trades_not_within_the_yardstick_and_is_none_for_share_lanes():
    s = _participation_lane([], open_rows=[{"size_vs_volume_pct": 1.0, "size_vs_oi_pct": 1.0}, {}, {"size_vs_volume_pct": 50.0, "size_vs_oi_pct": 1.0}])["participation"]
    assert s["closed_checked"] == 0 and s["open_not_within_cap"] == 2 and s["within_cap_realized_pnl"] is None
    from optplat.shortterm import lane_report
    from optplat.store import Store
    store = Store(":memory:")
    t0 = datetime(2026, 1, 5, 15, tzinfo=timezone.utc)
    tid = store.lane_open("share-lane", "SPY", t0, 100.0, 5, True, {})
    store.lane_close(tid, t0 + timedelta(hours=1), 101.0, "target", {})
    assert lane_report(store, "share-lane", True, t0, rules=[], limitations=[], symbols=["SPY"], exit_text={})["summary"]["participation"] is None


def test_participation_does_not_change_the_other_totals_and_the_dashboard_reads_it():
    import pathlib
    s = _participation_lane([(1.0, 1.5, {"size_vs_volume_pct": 50.0, "size_vs_oi_pct": 50.0})])
    assert s["realized_pnl"] == 100.0 and s["participation"]["within_cap"] == 0
    js = (pathlib.Path(__file__).parents[1] / "src/optplat/static/app.js").read_text()
    assert "participationNote" in js and "within_cap_realized_pnl" in js and "innerHTML" not in js


def test_the_two_tier_functions_have_pinned_argument_order_and_disjoint_labels():
    """Both were once called liquidity_tier with all-numeric, differently ordered arguments. A swapped call must not pass quietly."""
    from optplat import signals
    from optplat.liquidity import exit_liquidity_tier
    # exit tier: (volume, open_interest, spread_pct)
    assert exit_liquidity_tier(500, 2000, 4.0) == "PREFERRED"
    assert exit_liquidity_tier(4.0, 500, 2000) == "THIN"  # swapped order grades worse, not the same
    # signal tier: (spread_pct, volume, oi)
    assert signals.signal_liquidity_tier(4.0, 150, 1500) == "A"
    assert signals.signal_liquidity_tier(150, 1500, 4.0) == "C"
    # label sets never overlap, so mixing them up shows in output
    assert {"PREFERRED", "WATCH", "THIN"}.isdisjoint({"A", "B", "C"})
    # old names still point at the same functions
    assert signals.liquidity_tier is signals.signal_liquidity_tier


def test_best_trade_dependence_shows_a_total_that_is_one_lucky_trade():
    # qty 2, multiplier 100: pnl = (exit - entry) * 200. Three small losses and one big win.
    s = _participation_lane([(1.0, 0.9, {}), (1.0, 0.9, {}), (1.0, 0.9, {}), (1.0, 3.0, {})])
    d = s["best_trade_dependence"]
    assert s["realized_pnl"] == 400.0 - 60.0
    assert (d["closed"], d["best_trade_pnl"], d["realized_pnl_without_best"]) == (4, 400.0, -60.0)
    assert d["positive_without_best"] is False and d["best_share_of_total_pct"] == round(400 / 340 * 100, 1)


def test_best_trade_dependence_when_the_edge_is_spread_and_when_too_few_trades():
    d = _participation_lane([(1.0, 1.5, {}), (1.0, 1.5, {}), (1.0, 2.0, {})])["best_trade_dependence"]
    assert d["positive_without_best"] is True and d["realized_pnl_without_best"] == 200.0
    assert _participation_lane([(1.0, 1.5, {})])["best_trade_dependence"] is None
    assert _participation_lane([])["best_trade_dependence"] is None


def test_best_trade_dependence_has_no_share_when_total_is_not_positive_and_dashboard_wires_it():
    d = _participation_lane([(1.0, 0.5, {}), (1.0, 0.9, {})])["best_trade_dependence"]
    assert d["best_share_of_total_pct"] is None and d["positive_without_best"] is False
    import pathlib
    js = (pathlib.Path(__file__).parents[1] / "src/optplat/static/app.js").read_text()
    assert "best_trade_dependence" in js and "bestTradeNote" in js and "innerHTML" not in js
