"""Plain-English help for cycle and lane errors (display only)."""
import io
import json
from dataclasses import replace
from urllib.error import HTTPError

from fastapi.testclient import TestClient

from optplat.errorhelp import AGENT, DESIGN, OWNER, REPEAT_ALERT, WAIT, error_report, explain, explain_cycle
from optplat.fallback_data import IBKRWithYahooFallback
from optplat.ibkr_data import ServiceError, service_error
from helpers import NOW
from test_dataquality import build, snapshot
from test_fallback_data import FakeIBKR, FakeYahoo, _snap

NVDA_EMPTY = "data NVDA: rejected (EMPTY_CHAIN: no usable option rows (started with 0))"


def test_the_nvda_empty_chain_reads_as_a_one_off_wait_with_its_source():
    h = explain(NVDA_EMPTY, {"NVDA": "data from yahoo-fallback; IBKR failed: ServiceError: HTTP 503 SNAPSHOT_DEADLINE"})
    assert h["kind"] == "EMPTY_CHAIN" and h["symbol"] == "NVDA" and h["who"] == WAIT
    assert "NVDA" in h["cause"] and "SNAPSHOT_DEADLINE" in h["cause"] and "skipped" in h["fix"]


def test_clock_errors_need_the_owner_and_alert_at_once():
    [h] = explain_cycle(["data SPY: rejected (FUTURE_TIMESTAMP: snapshot is 6s ahead of the clock)"])
    assert h["who"] == OWNER and h["alert"] and "Set time and date automatically" in h["fix"]


def test_repeats_count_consecutive_cycles_and_reset_when_an_error_clears():
    first = explain_cycle([NVDA_EMPTY])
    assert first[0]["repeats"] == 1 and not first[0]["alert"]
    prev = first
    for _ in range(REPEAT_ALERT - 1):
        prev = explain_cycle([NVDA_EMPTY], prev)
    assert prev[0]["repeats"] == REPEAT_ALERT and prev[0]["alert"]
    other = explain_cycle(["data SPY: rejected (EMPTY_CHAIN: no usable option rows (started with 0))"], prev)
    assert other[0]["repeats"] == 1  # a different symbol is a different problem
    assert explain_cycle([NVDA_EMPTY], explain_cycle([], prev))[0]["repeats"] == 1


def test_duplicate_errors_in_one_cycle_are_listed_once():
    assert len(explain_cycle([NVDA_EMPTY, NVDA_EMPTY])) == 1


def test_paused_lane_marks_are_a_design_decision_not_an_alarm():
    h = explain("IBKR BBO exchange time unverified; simulated marks and fills paused")
    assert h["kind"] == "LANE_MARKS_PAUSED" and h["who"] == DESIGN and h["symbol"] is None
    assert not explain_cycle([h["error"]])[0]["alert"]


def test_code_errors_point_at_the_file_and_unknown_errors_go_to_an_agent():
    h = explain("AttributeError: 'NoneType' object has no attribute 'bid' [optionlanes.py:412 in _step_short]")
    assert h["kind"] == "CODE_ERROR" and h["who"] == AGENT
    assert h["code"] == {"file": "optionlanes.py", "line": 412, "function": "_step_short"}
    u = explain("something nobody has seen")
    assert u["kind"] == "UNKNOWN" and u["who"] == AGENT


def test_error_report_explains_lane_errors_and_a_failed_mirror_order():
    cycle = {"started_at": "t", "errors": [NVDA_EMPTY]}  # stored before error_help existed: explained on read
    lanes = [("short", "Short", {"at": "t2", "errors": ["AAPL: chain unavailable (KeyError: 'x')", "AAPL: chain unavailable (KeyError: 'x')"]}),
             ("swing", "Swing", {"errors": []}), ("flow", "Flow", None)]
    rep = error_report(cycle, lanes, {"state": "error", "kind": "ibkr_mirror_error", "at": "t3"})
    assert rep["cycle"]["items"][0]["kind"] == "EMPTY_CHAIN"
    assert [lane["lane"] for lane in rep["lanes"]] == ["short"] and len(rep["lanes"][0]["items"]) == 1
    assert rep["other"][0]["kind"] == "MIRROR_ERROR" and rep["alerts"] >= 1
    assert error_report(None, [], None)["alerts"] == 0


def test_a_service_refusal_keeps_its_status_and_reason():
    body = json.dumps({"error": "IBKR data unavailable", "reason": "SNAPSHOT_DEADLINE"}).encode()
    exc = service_error(HTTPError("http://127.0.0.1:8791/v1/snapshot", 503, "x", {}, io.BytesIO(body)))
    assert isinstance(exc, ServiceError) and str(exc) == "HTTP 503 SNAPSHOT_DEADLINE"
    assert str(service_error(HTTPError("u", 400, "x", {}, io.BytesIO(b"not json")))) == "HTTP 400"


def test_fallback_remembers_why_each_chain_left_ibkr_and_forgets_on_recovery():
    ibkr = FakeIBKR(fail=True)
    wrap = IBKRWithYahooFallback(ibkr, FakeYahoo, clock=lambda: NOW)
    wrap.snapshot("AAA")
    assert wrap.last_chain_why["AAA"].startswith("IBKR failed: ConnectionError: service down")
    ibkr.fail, ibkr.snap = False, _snap("ibkr-shared-research-only")
    wrap.snapshot("AAA")
    assert "AAA" not in wrap.last_chain_why


def test_engine_stores_explained_errors_and_counts_them_across_cycles():
    engine, manager, broker, provider, clock = build(auto_entries=True)
    provider.set_snapshot(replace(snapshot(), underlying=0.0))
    first = engine.run_cycle()
    [h] = [i for i in first["error_help"] if i["kind"] == "BAD_DATA"]
    assert h["repeats"] == 1 and h["symbol"] == "AAA" and "data from" in h["cause"]
    second = engine.run_cycle()
    assert [i for i in second["error_help"] if i["kind"] == "BAD_DATA"][0]["repeats"] == 2
    assert engine.last_cycle()["error_help"] == second["error_help"]


def test_errors_api_needs_the_token_and_returns_the_report():
    from optplat.api import create_app
    from optplat.engine import Runner
    engine, manager, broker, provider, clock = build(auto_entries=True)
    provider.set_snapshot(replace(snapshot(), underlying=0.0))
    engine.run_cycle()
    token = "t" * 24
    runner = Runner(engine)
    with TestClient(create_app(manager, token, engine, runner)) as c:
        assert c.get("/api/errors").status_code == 401
        rep = c.get("/api/errors", headers={"X-API-Token": token}).json()
    runner.stop()
    assert rep["cycle"]["items"] and "nothing here retries" in rep["note"]


def test_a_spent_ibkr_bar_budget_is_named_and_points_at_platform_usage():
    h = explain("data SPY: RuntimeError: IBKR failed: ServiceError: HTTP 503 Historical pacing budget exhausted; Yahoo fallback unavailable")
    assert h["kind"] == "IBKR_BUDGET" and "platform_usage" in h["fix"]
