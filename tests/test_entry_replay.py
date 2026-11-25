from datetime import date, datetime, timedelta, timezone

from optplat import entry_replay as er

TODAY = date(2026, 12, 31)
D0 = date(2026, 11, 2)


def day(i):
    return (D0 + timedelta(days=i)).isoformat()


def follow(i, sym, spread, bid_later, c=None):
    """One follow on day i with a one-point path: the bid on the next day decides the baseline exit."""
    contract = c or f"{sym}{i}"
    f = {"contract": contract, "symbol": sym, "followed_day": day(i), "entry_ask": 2.0, "expiry": "2027-03-19", "volume": 100,
         "spread_pct": spread, "right": "C", "dte": 60}
    p = {"contract": contract, "followed_day": day(i), "ts": datetime(2026, 11, 3, tzinfo=timezone.utc).isoformat(),
         "observed_day": day(i + 1), "age": 1, "bid": bid_later, "ask": bid_later + 0.1}
    return f, p


def build(treat_bid, ctrl_bid, n=20):
    fs, ps = [], []
    for i in range(n):
        for j in range(3):
            f, p = follow(i, f"T{j}", 3.0, treat_bid)
            g, q = follow(i, f"C{j}", 8.0, ctrl_bid)
            fs += [f, g]
            ps += [p, q]
    return fs, ps


def test_clear_difference_passes_the_mechanical_bar_and_uses_the_later_dates():
    fs, ps = build(treat_bid=3.0, ctrl_bid=1.3)  # treatment takes profit (+50%), control stops out (-35%)
    rows = er.outcomes(fs, ps, TODAY)
    r = er.compare_hypothesis("E1", rows)
    assert r["plan_bar_mechanical"] and r["mean_diff_pct"] > 50
    assert r["ci95_pct"][0] > 0 and r["mean_diff_without_top3_pct"] > 0
    assert len(r["later_dates"]) == 6 and set(r["later_dates"]) <= {day(i) for i in range(20)}
    assert r["independent"] == {"treatment": 60, "control": 60}  # one per underlying per day; 3 names x 20 days


def test_no_difference_does_not_pass_and_strikes_of_one_name_count_once():
    fs, ps = build(3.0, 3.0)
    extra, extra_p = follow(0, "T0", 3.0, 3.0, c="T0-other")
    r = er.compare_hypothesis("E1", er.outcomes(fs + [extra], ps + [extra_p], TODAY))
    assert not r["plan_bar_mechanical"] and r["independent"]["treatment"] == 60  # the extra strike adds no observation


def test_unknown_features_and_unresolved_paths_are_left_out_not_guessed():
    fs, ps = build(3.0, 1.3, n=10)
    for f in fs[:6]:
        f.pop("spread_pct")
    ps = [p for p in ps if p["contract"] != "T10"]  # no path for one contract: unresolved
    r = er.compare_hypothesis("E1", er.outcomes(fs, ps, TODAY))
    assert r["unknown_feature"] == 6
    assert er.compare_hypothesis("E2", er.outcomes(fs, ps, TODAY))["unknown_feature"] == len(fs)  # no iv_percentile recorded at all


def test_too_few_observations_makes_no_statement():
    fs, ps = build(3.0, 1.3, n=2)
    r = er.compare_hypothesis("E1", er.outcomes(fs, ps, TODAY))
    assert r["mean_diff_pct"] is None and r["plan_bar_mechanical"] is False and "too few" in r["note"]


def test_group_definitions():
    assert er.e1({"spread_pct": 5}) is True and er.e1({"spread_pct": 7}) is False and er.e1({"spread_pct": 12}) is None
    assert er.e3({"dte": 45}) is True and er.e3({"dte": 100}) is False and er.e3({"dte": 20}) is None
    assert er.e4({"days_to_earnings": 3}) is False and er.e4({"days_to_earnings": 20}) is True and er.e4({"days_to_earnings": None}) is None
    assert er.r1({"right": "P", "regime_blocks_puts": True}) is False and er.r1({"right": "C", "regime_blocks_calls": False}) is True
    assert er.r1({"right": "P"}) is None
    assert er.s1({"chosen_by": [{"strategy": "liquid", "rank": 1}]}) is True
    assert er.s1({"chosen_by": [{"strategy": "liquid", "rank": 2}]}) is False
    assert er.s1({"chosen_by": [{"strategy": "lane:x", "rank": 1}]}) is None and er.s1({}) is None


def test_callouts_are_never_mixed_in():
    f, p = follow(0, "AAA", 3.0, 3.0)
    f["source"] = "callout:someone"
    assert er.outcomes([f], [p], TODAY) == []


def test_e6_groups_calls_after_earnings_against_calls_before():
    assert er.e6({"right": "C", "days_since_earnings": 2}) is True
    assert er.e6({"right": "C", "days_since_earnings": 5}) is None  # neither window
    assert er.e6({"right": "C", "days_to_earnings": 4}) is False
    assert er.e6({"right": "C", "days_to_earnings": 12}) is None
    assert er.e6({"right": "P", "days_since_earnings": 2}) is None  # calls only
    assert er.e6({"right": "C"}) is None  # unknown is left out, never guessed
    assert "E6" in er.HYPOTHESES
