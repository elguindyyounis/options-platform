"""SW1 / ST1: the registered criteria behave as written. All trades here are synthetic test fixtures."""
from datetime import date, datetime, timedelta, timezone

from optplat import lane_hypotheses as lh


def trade(lane, symbol, day, ret_pct, *, hold_days=0, fictional=False, closed=True, hour=15):
    opened = datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)
    closed_at = opened + timedelta(days=hold_days, minutes=30)
    return {"lane": lane, "symbol": symbol, "opened_at": opened.isoformat(), "entry_price": 100.0,
            "closed_at": closed_at.isoformat() if closed else None,
            "exit_price": 100.0 * (1 + ret_pct / 100) if closed else None, "fictional": int(fictional)}


def sessions(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


SYMS = ["SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA"]


def st1_trades(ret_for, days=25, per_day=4, start=date(2026, 11, 30)):
    out = []
    for i, d in enumerate(sessions(start, days)):
        for j in range(per_day):
            out.append(trade(lh.ST1.lane, SYMS[j], d, ret_for(i, j)))
    return out


def test_only_trades_opened_after_registration_count():
    early = [trade(lh.ST1.lane, "SPY", date(2026, 11, 20), 5.0), trade(lh.ST1.lane, "QQQ", date(2026, 11, 26), 5.0)]
    late = [trade(lh.ST1.lane, "SPY", date(2026, 11, 27), 1.0)]
    obs, used, _ = lh.observations(lh.ST1, early + late)
    assert used == 1 and [o["day"] for o in obs] == ["2026-11-27"]


def test_fictional_open_and_other_lane_trades_are_ignored():
    d = date(2026, 12, 1)
    rows = [trade(lh.ST1.lane, "SPY", d, 1, fictional=True), trade(lh.ST1.lane, "SPY", d, 1, closed=False),
            trade(lh.SW1.lane, "SPY", d, 1)]
    assert lh.observations(lh.ST1, rows)[0] == []


def test_one_observation_per_name_per_day_after_stress():
    d = date(2026, 12, 1)
    obs, used, _ = lh.observations(lh.ST1, [trade(lh.ST1.lane, "SPY", d, 1.0), trade(lh.ST1.lane, "SPY", d, 3.0, hour=17)])
    assert used == 2 and len(obs) == 1
    assert abs(obs[0]["ret_pct"] - (2.0 - lh.ST1.stress_pct)) < 1e-9


def test_collecting_until_the_fixed_sample_exists():
    r = lh.evaluate(lh.ST1, st1_trades(lambda i, j: 1.0, days=5))
    assert r["verdict"] == "COLLECTING" and r["observations"] == 20


def test_consistent_positive_net_expectancy_passes():
    r = lh.evaluate(lh.ST1, st1_trades(lambda i, j: 0.5 + 0.1 * ((i + j) % 3)))
    assert r["verdict"] == "PASSED_CRITERIA" and r["mean_without_top3_pct"] > 0 and r["ci_later_pct"][0] > 0


def test_gross_gain_smaller_than_the_stress_cost_fails():
    r = lh.evaluate(lh.ST1, st1_trades(lambda i, j: 0.05))
    assert r["verdict"] == "FAILED_CRITERIA"


def test_a_few_big_winners_cannot_carry_it():
    big = {(20, 0), (21, 1), (22, 2), (23, 3)}
    r = lh.evaluate(lh.ST1, st1_trades(lambda i, j: 40.0 if (i, j) in big else -0.3))
    assert r["verdict"] == "FAILED_CRITERIA"


def test_verdict_is_fixed_by_the_first_sample_not_by_later_trades():
    bad = st1_trades(lambda i, j: -0.5)
    good_later = st1_trades(lambda i, j: 3.0, start=date(2027, 2, 1))
    first = lh.evaluate(lh.ST1, bad)
    assert first["verdict"] == "FAILED_CRITERIA"
    again = lh.evaluate(lh.ST1, bad + good_later)
    assert again["verdict"] == "FAILED_CRITERIA" and again["sample_to"] == first["sample_to"]


def test_a_concentrated_sample_fails_rather_than_waiting():
    rows = []
    for d in sessions(date(2026, 11, 30), 10):  # 100 observations in 10 days: fewer than min_days 20
        for s in range(10):
            rows.append(trade(lh.ST1.lane, f"S{s}", d, 2.0))
    r = lh.evaluate(lh.ST1, rows)
    assert r["verdict"] == "FAILED_CRITERIA" and "concentrated" in r["reason"]


def spy_series(start, days, daily_pct):
    closes, px = {}, 100.0
    for d in sessions(start - timedelta(days=10), days + 20):
        closes[d] = px
        px *= 1 + daily_pct / 100
    return closes


def sw1_trades(ret_pct, start=date(2026, 11, 30)):
    out = []
    for i, d in enumerate(sessions(start, 20)):
        for j in range(3):
            out.append(trade(lh.SW1.lane, f"N{(i * 3 + j) % 25}", d, ret_pct, hold_days=7))
    return out


def test_sw1_measures_against_spy_over_the_same_dates():
    # Every swing trade gains 3%, but SPY gains about 5% over each 7-calendar-day hold: SW1 fails.
    r = lh.evaluate(lh.SW1, sw1_trades(3.0), spy_series(date(2026, 11, 30), 40, 1.0))
    assert r["verdict"] == "FAILED_CRITERIA" and r["mean_pct"] < 0
    flat = lh.evaluate(lh.SW1, sw1_trades(3.0), spy_series(date(2026, 11, 30), 40, 0.0))
    assert flat["verdict"] == "PASSED_CRITERIA"


def test_sw1_without_spy_closes_gives_no_verdict():
    r = lh.evaluate(lh.SW1, sw1_trades(3.0), {})
    assert r["verdict"] == "NO_VERDICT_DATA" and r["trades_unmatched"] == 60


def test_registrations_are_dated_after_today_and_stricter_than_the_plan_bar():
    for h in lh.REGISTERED:
        assert h.first_day > date(2026, 11, 26) and h.stress_pct > 0 and h.sample >= 60
    assert lh.FAMILY_SIZE >= len(lh.REGISTERED)


def test_report_reads_real_trades_and_survives_a_failed_spy_fetch():
    class Store:
        def lane_trades(self, lane, fictional, limit=300):
            assert fictional is False
            return []

    class Broken:
        def daily_bars(self, *_a, **_k):
            raise RuntimeError("offline")

    r = lh.report(Store(), Broken())
    assert [x["id"] for x in r] == ["SW1", "ST1"] and all(x["verdict"] == "COLLECTING" for x in r)
