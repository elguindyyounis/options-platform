from optplat.scoreboard import MIN_TRADES_FOR_VERDICT, lane_scoreboard, scoreboard


def tr(net, stress=None):
    pm = {"net_pct": net}
    if stress is not None:
        pm["stress_net_pct"] = stress
    return {"close_payload": {"postmortem": pm}}


def test_no_trades_and_missing_postmortems_are_reported_as_such():
    assert lane_scoreboard([])["verdict"] == "NO_TRADES"
    assert lane_scoreboard([{"close_payload": None}, {"close_payload": {}}])["trades"] == 0


def test_a_good_looking_lane_with_few_trades_is_too_few_to_say():
    row = lane_scoreboard([tr(40, 35)] * (MIN_TRADES_FOR_VERDICT - 1))
    assert row["verdict"] == "TOO_FEW" and row["avg_net_pct"] == 40


def test_stressed_view_is_shown_and_judges_the_verdict():
    rows = [tr(10 + (i % 3), -5 - (i % 3)) for i in range(MIN_TRADES_FOR_VERDICT)]
    row = lane_scoreboard(rows)
    assert row["avg_net_pct"] > 0 > row["avg_stressed_pct"]
    assert row["winners_pct"] == 100 and row["winners_stressed_pct"] == 0
    assert row["verdict"] == "BELOW_ZERO"  # the bid view looks fine, the stricter view does not


def test_noise_around_zero_is_indistinguishable_from_zero():
    rows = [tr(x) for x in [30, -30] * (MIN_TRADES_FOR_VERDICT // 2)]
    assert lane_scoreboard(rows)["verdict"] == "INDISTINGUISHABLE_FROM_ZERO"


def test_a_clear_gain_is_above_zero_and_a_single_big_win_is_not():
    steady = [tr(20 + (i % 4)) for i in range(MIN_TRADES_FOR_VERDICT)]
    assert lane_scoreboard(steady)["verdict"] == "ABOVE_ZERO"
    carried = [tr(900)] + [tr(1 + (i % 2)) for i in range(MIN_TRADES_FOR_VERDICT - 1)]
    row = lane_scoreboard(carried)
    assert row["verdict"] == "CARRIED_BY_ONE_TRADE" and row["best_trade_share_pct"] > 50


def test_more_lanes_compared_widens_the_interval():
    rows = [tr(x) for x in [5, 15, -5, 25, 10, 0, 20, -10] * 5]
    one = lane_scoreboard(rows, 1)["interval_pct"]
    five = lane_scoreboard(rows, 5)["interval_pct"]
    assert five[0] < one[0] and five[1] > one[1]


def test_missing_stress_number_falls_back_to_the_bid_number_not_a_better_one():
    row = lane_scoreboard([tr(10), tr(-4)])
    assert row["avg_stressed_pct"] == row["avg_net_pct"]


def test_scoreboard_counts_lanes_and_carries_the_caveat():
    sb = scoreboard({"a": [tr(5)], "b": []})
    assert sb["lanes_compared"] == 2 and "proof" in sb["note"] and sb["lanes"]["b"]["verdict"] == "NO_TRADES"


def test_unscored_closed_trades_are_counted_not_silently_dropped():
    row = lane_scoreboard([tr(5, 5), {"close_payload": None}, {"close_payload": {"postmortem": {"net_pct": None}}}])
    assert row["trades"] == 1 and row["closed_total"] == 3 and row["unscored"] == 2


def test_a_positive_reading_is_withheld_when_too_many_closed_trades_are_unscored():
    scored = [tr(20 + (i % 4), 18 + (i % 4)) for i in range(MIN_TRADES_FOR_VERDICT)]
    assert lane_scoreboard(scored)["verdict"] == "ABOVE_ZERO"
    # the lane's losers have no post-mortem: the scored trades alone look great, the lane as a whole is unknown
    hidden_losers = scored + [{"close_payload": None}] * 10
    row = lane_scoreboard(hidden_losers)
    assert row["verdict"] == "INCOMPLETE_DATA" and row["unscored"] == 10


def test_missing_stress_figures_are_counted_but_do_not_change_the_reading():
    rows = [tr(20 + (i % 4)) for i in range(MIN_TRADES_FOR_VERDICT)]  # no stress figure on any trade
    row = lane_scoreboard(rows)
    assert row["stress_missing"] == MIN_TRADES_FOR_VERDICT and row["verdict"] == "ABOVE_ZERO"


def test_a_small_gap_does_not_change_the_reading_and_negative_readings_are_never_softened():
    rows = [tr(20 + (i % 4), 18 + (i % 4)) for i in range(MIN_TRADES_FOR_VERDICT * 4)] + [{"close_payload": None}]
    assert lane_scoreboard(rows)["verdict"] == "ABOVE_ZERO"  # 1 of 121 missing is under the 10% bar
    bad = [tr(10, -5 - (i % 3)) for i in range(MIN_TRADES_FOR_VERDICT)] + [{"close_payload": None}] * 10
    assert lane_scoreboard(bad)["verdict"] == "BELOW_ZERO"
