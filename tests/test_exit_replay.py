from datetime import date, datetime, timedelta, timezone

from optplat import exit_replay as xr
from optplat.exit_replay import BASELINE, ExitRule
from optplat.store import Store

D0 = date(2026, 11, 9)
TODAY = date(2026, 12, 31)


def follow(contract="C1", symbol="AAA", day="2026-11-09", ask=2.0, expiry="2027-03-19", vol=100):
    return {"contract": contract, "symbol": symbol, "followed_day": day, "entry_ask": ask, "expiry": expiry, "volume": vol}


def pt(age, bid, ask=None, day="2026-11-09", contract="C1", observed=None, n=0):
    ts = (datetime(2026, 11, 9, 16, tzinfo=timezone.utc) + timedelta(hours=age * 24 + n)).isoformat()
    return {"contract": contract, "followed_day": day, "ts": ts, "observed_day": observed or (D0 + timedelta(days=age)).isoformat(),
            "age": age, "bid": bid, "ask": ask if ask is not None else bid + 0.1}


def run(rule, points, f=None):
    return xr.replay(rule, [f or follow()], points, TODAY)[0]


def test_take_profit_sells_at_the_bid_of_the_point_that_fired_not_at_the_level():
    r = run(BASELINE, [pt(1, 2.2), pt(2, 3.2)])  # +60% seen at once: a gap past the 40% level
    assert r["reason"] == "take_profit" and round(r["ret"], 4) == 0.6 and r["age"] == 2
    assert r["ret_stressed"] < r["ret"]  # half the spread comes off


def test_stop_is_checked_before_take_profit_and_fires():
    assert run(BASELINE, [pt(1, 1.3)])["reason"] == "stop"
    rule = ExitRule("both", take_profit_pct=-50, stop_loss_pct=0)  # both true at once: the pessimistic order wins
    assert run(rule, [pt(1, 1.0)])["reason"] == "stop"


def test_time_stop_and_expiry_margin():
    assert run(ExitRule("t", time_stop_days=5), [pt(2, 2.1), pt(5, 2.1)])["reason"] == "time_stop"
    near = follow(expiry="2026-11-18")
    assert run(BASELINE, [pt(1, 2.0)], near)["reason"] == "horizon"  # observed the 10th, 8 days left: no margin exit; expired by TODAY
    assert run(BASELINE, [pt(1, 2.0, observed="2026-11-14")], near)["reason"] == "expiry_margin"  # 4 days left


def test_trailing_stop_arms_after_the_gain_then_exits_below_the_peak():
    rule = ExitRule("trail", trail_after_pct=30, trail_pct=15)
    r = run(rule, [pt(1, 2.7), pt(2, 3.0), pt(3, 2.6)])  # peak +50%, falls to +30%: 20 points below
    assert r["reason"] == "trail" and round(r["ret"], 2) == 0.3
    assert run(rule, [pt(1, 2.2), pt(2, 1.8)])["reason"] != "trail"  # never armed


def test_unresolved_paths_are_counted_not_guessed():
    r = run(BASELINE, [pt(1, 2.1), pt(2, 2.2)], follow(expiry="2027-03-19"))
    assert r["resolved"] is False
    now_in_range = xr.replay(BASELINE, [follow()], [pt(1, 2.1)], date(2026, 11, 12))[0]
    assert now_in_range["resolved"] is False
    s = xr.summarize([r])
    assert s["unresolved"] == 1 and s["mean_return_pct"] is None


def test_horizon_when_the_path_reaches_30_days():
    r = run(BASELINE, [pt(10, 2.1), pt(30, 2.2)])
    assert r["reason"] == "horizon" and r["age"] == 30


def test_no_entry_ask_or_missing_points_are_unresolved():
    assert xr.replay(BASELINE, [follow(ask=0)], [], TODAY)[0]["resolved"] is False
    assert xr.replay(BASELINE, [follow()], [], TODAY)[0]["resolved"] is False


def test_replay_uses_one_observation_per_underlying_day():
    fs = [follow("C1", vol=10), follow("C2", vol=900), follow("C3", symbol="BBB", vol=1)]
    pts = [pt(1, 3.0, contract=c) for c in ("C1", "C2", "C3")]
    rows = xr.replay(BASELINE, fs, pts, TODAY)
    assert sorted(r["contract"] for r in rows) == ["C2", "C3"]


def _rows(day_returns):
    return [{"contract": f"c{i}", "followed_day": d, "resolved": True, "ret": x, "ret_stressed": x, "age": 1, "reason": "x", "symbol": "S"}
            for i, (d, x) in enumerate(day_returns)]


def test_compare_uses_later_30_percent_and_drops_top_three():
    days = [f"2026-11-{d:02d}" for d in range(1, 11)]
    base = _rows([(d, 0.0) for d in days for _ in range(5)])
    better = _rows([(d, 0.10) for d in days for _ in range(5)])
    out = xr.compare(better, base)
    assert out["later_days"] == days[-3:] and out["later_observations"] == 15
    assert out["mean_diff_pct"] == 10.0 and out["ci95_pct"] == [10.0, 10.0] and out["plan_bar_mechanical"] is True
    assert out["robustness"]["ci_day_clustered"] == [10.0, 10.0] and out["robustness"]["subperiod_means"] == [10.0] * 3
    assert xr.compare(better, base) == out  # deterministic
    # one big winner carries it: removing the three best observations kills the pass
    carried = _rows([(d, 0.0) for d in days for _ in range(5)])
    for r in carried[-3:]:
        r["ret"] = r["ret_stressed"] = 5.0
    assert xr.compare(carried, base)["plan_bar_mechanical"] is False


def test_compare_with_too_few_pairs_says_so():
    one = _rows([("2026-11-01", 0.1)])
    out = xr.compare(one, _rows([("2026-11-01", 0.0)]))
    assert out["plan_bar_mechanical"] is False and out["mean_diff_pct"] is None


def test_grid_matches_the_plan():
    names = [r.name for r in xr.grid_rules()]
    # +2 at the end: X5 registered 2026-11-27 (a deliberate owner-directed addition, not a weakened check)
    assert names[0] == BASELINE.name and len(names) == 1 + 8 + 2 + 1 + 2 and len(set(names)) == len(names)


def test_report_and_api():
    from fastapi.testclient import TestClient
    from optplat.api import create_app
    from optplat.broker import SimBroker
    from optplat.engine import EngineConfig, TradingEngine
    from optplat.marketdata import DemoDataProvider
    from optplat.orders import OrderManager
    from optplat.strategy import LiquidTrendStrategy

    s = Store(":memory:")
    rep = xr.report(s, True, TODAY)
    assert rep["fictional"] is True and rep["rules"][0]["observations"] == 0 and rep["rules_tried"] == len(rep["rules"]) - 1
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    with TestClient(create_app(manager, "t" * 24, engine, None)) as c:
        assert c.get("/api/shadow/exits").status_code == 401
        assert c.get("/api/shadow/exits", headers={"X-API-Token": "t" * 24}).json()["fictional"] is True


X5 = ExitRule("x5", take_profit_pct=80, stop_loss_pct=30, trim_at_pct=20)


def test_x5_trims_half_then_stops_to_entry_and_blends_both_halves():
    r = run(X5, [pt(1, 2.5), pt(2, 1.9)])  # +25% trims half; then the bid is below entry: stop to entry on the rest
    assert r["reason"] == "stop_to_entry" and round(r["ret"], 4) == round(0.5 * 0.25 + 0.5 * -0.05, 4)
    assert r["ret_stressed"] < r["ret"]


def test_x5_rest_can_run_to_the_take_profit_and_without_a_trim_it_is_the_plain_stop():
    r = run(X5, [pt(1, 2.5), pt(2, 3.8)])
    assert r["reason"] == "take_profit" and round(r["ret"], 4) == round(0.5 * 0.25 + 0.5 * 0.9, 4)
    assert run(X5, [pt(1, 1.3)])["reason"] == "stop" and round(run(X5, [pt(1, 1.3)])["ret"], 4) == -0.35


def test_x5_gap_straight_past_take_profit_sells_everything_once():
    r = run(X5, [pt(1, 4.0)])
    assert r["reason"] == "take_profit" and round(r["ret"], 4) == 1.0


def test_x5_rules_are_in_the_grid_and_the_baseline_is_unchanged():
    names = [x.name for x in xr.grid_rules()]
    assert sum(n.startswith("X5") for n in names) == 2
    assert all(x.trim_at_pct is None for x in xr.grid_rules() if not x.name.startswith("X5"))
