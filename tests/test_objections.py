from fastapi.testclient import TestClient

from optplat import objections as ob
from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, TradingEngine
from optplat.marketdata import DemoDataProvider
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy


def rows(source, n, pct, label=None):
    return [{"source": source, "source_label": label or source, "status": "CLOSED", "pnl": pct, "pnl_pct": pct} for _ in range(n)]


def ids(out):
    return {o["id"]: o for o in out["objections"]}


def build(rs, tracker=None, clock=None, challenge=None, fictional=False):
    return ob.build(rs, tracker or {"total_marks": 500, "min_n": 20}, clock or {"behind_s": 0.5, "tolerance_s": 5}, challenge, fictional, "2026-11-17T00:00:00+00:00")


def test_fictional_data_is_always_the_first_objection():
    out = build(rows("a", 30, 5.0), fictional=True)
    assert out["objections"][0]["id"] == "fictional" and out["objections"][0]["severity"] == "high"
    assert "fictional" not in ids(build(rows("a", 30, 5.0), fictional=False))


def test_a_clock_over_the_limit_is_flagged_and_one_inside_it_is_not():
    assert "clock" in ids(build(rows("a", 30, 1.0), clock={"behind_s": 9.0, "tolerance_s": 5}))
    assert "clock" not in ids(build(rows("a", 30, 1.0), clock={"behind_s": 2.0, "tolerance_s": 5}))
    assert "clock" not in ids(build(rows("a", 30, 1.0), clock={"behind_s": None, "tolerance_s": 5}))


def test_lanes_under_the_minimum_are_called_too_small_and_the_count_is_exact():
    out = build(rows("a", 30, 1.0) + rows("b", 3, 1.0, "Lane B") + rows("c", 19, 1.0))
    o = ids(out)["sample"]
    assert "2 of 3" in o["evidence"] and o["severity"] == "medium"
    assert "sample" not in ids(build(rows("a", 30, 1.0) + rows("b", 20, 1.0)))
    assert ids(build(rows("a", 3, 1.0)))["sample"]["severity"] == "high"


def test_with_no_control_trades_the_rule_cannot_claim_anything():
    o = ids(build(rows(ob.RULE_LANE, 40, 20.0)))["control"]
    assert o["severity"] == "medium" and "coin flip" in o["title"] and "0 closed trades" in o["evidence"]


def test_a_rule_that_does_not_beat_the_control_by_the_margin_is_a_high_objection():
    out = build(rows(ob.RULE_LANE, 30, 10.0) + rows(ob.CONTROL_LANE, 30, 8.0))
    assert ids(out)["control"]["severity"] == "high" and "does not beat random" in ids(out)["control"]["title"]
    ahead = build(rows(ob.RULE_LANE, 30, 20.0) + rows(ob.CONTROL_LANE, 30, 8.0))
    assert ids(ahead)["control"]["severity"] == "low" and "not proof" in ids(ahead)["control"]["title"]


def test_the_best_of_many_lanes_is_flagged_but_the_control_is_never_named_the_best():
    rs = rows("a", 25, 4.0) + rows("b", 25, 9.0, "Lane B") + rows("c", 25, 1.0) + rows(ob.CONTROL_LANE, 25, 50.0)
    o = ids(build(rs))["best_of_many"]
    assert "Lane B" in o["evidence"] and "4 lanes" in o["evidence"]
    assert "best_of_many" not in ids(build(rows("a", 25, 4.0) + rows("b", 25, 9.0)))


def test_a_thin_tracker_and_a_restarting_challenge_are_flagged_with_their_own_numbers():
    out = build(rows("a", 30, 1.0), tracker={"total_marks": 7, "min_n": 20}, challenge={"attempts_finished": 6, "outcomes": {"TARGET": 1}})
    assert "7 marks" in ids(out)["tracker"]["evidence"] and "1 of 6" in ids(out)["challenge"]["evidence"]
    assert "tracker" not in ids(build(rows("a", 30, 1.0))) and "challenge" not in ids(build(rows("a", 30, 1.0), challenge={"attempts_finished": 0, "outcomes": {}}))


def test_objections_are_sorted_most_severe_first_and_each_says_what_would_change_its_mind():
    out = build(rows("a", 3, 1.0), fictional=True, clock={"behind_s": 9.0, "tolerance_s": 5}, tracker={"total_marks": 0, "min_n": 20})
    order = [ob.SEVERITY_ORDER[o["severity"]] for o in out["objections"]]
    assert order == sorted(order)
    assert all(o["evidence"] and o["why_it_matters"] and o["would_change_my_mind"] for o in out["objections"])
    assert "not evidence of an edge" in out["note"]


def test_open_trades_and_missing_results_are_not_counted():
    rs = rows("a", 25, 1.0) + [{"source": "a", "source_label": "a", "status": "OPEN", "pnl": None, "pnl_pct": None},
                               {"source": "a", "source_label": "a", "status": "CLOSED", "pnl": None, "pnl_pct": None}]
    lane = ob.lane_table(rs)[0]
    assert lane["n"] == 25 and lane["open"] == 1


def test_the_endpoint_needs_the_token_and_works_on_an_empty_platform():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    with TestClient(create_app(manager, "t" * 24, engine, None)) as c:
        assert c.get("/api/objections").status_code == 401
        body = c.get("/api/objections", headers={"X-API-Token": "t" * 24}).json()
    assert body["fictional"] is True and body["objections"][0]["id"] == "fictional" and "control" in {o["id"] for o in body["objections"]}


def test_a_platform_with_no_closed_trades_says_so_instead_of_staying_quiet():
    o = ids(build([]))["sample"]
    assert o["severity"] == "high" and "Nothing has closed" in o["title"]
    only_open = [{"source": "a", "source_label": "a", "status": "OPEN", "pnl": None, "pnl_pct": None}]
    assert "Nothing has closed" in ids(build(only_open))["sample"]["title"]
