import math

from test_engine import build

from optplat.liquidity import liquidity_evidence


def ev(**kw):
    args = dict(bid=4.90, ask=5.10, volume=200, open_interest=2000, quantity=1)
    args.update(kw)
    return liquidity_evidence(**args)


def test_liquid_small_order_has_no_flags_and_is_scenario_only():
    r = ev()
    assert r["flags"] == [] and r["status"] == "SCENARIO_ONLY"
    assert [s["scenario"] for s in r["exit_scenarios"]] == ["BASE_BID", "THIN_MARKET", "STRESSED_EXIT"]


def test_scenarios_never_improve_on_the_base_case():
    s = [x["modeled_exit_usd"] for x in ev(quantity=30)["exit_scenarios"]]
    assert s[0] >= s[1] >= s[2] >= 0


def test_large_participation_is_flagged():
    r = ev(quantity=30, volume=100, open_interest=200)
    assert r["volume_participation_pct"] == 30.0
    assert any("daily volume" in f for f in r["flags"]) and any("open interest" in f for f in r["flags"])


def test_missing_or_bad_inputs_fail_closed_with_flags():
    r = ev(volume=None, open_interest=0)
    assert any("volume missing" in f for f in r["flags"]) and any("open interest missing" in f for f in r["flags"])
    # missing depth is treated as maximum participation, so the stress case is the harshest allowed
    assert r["exit_scenarios"][1]["bid_concession_pct"] >= 50
    bad = ev(bid=float("nan"))
    assert bad["exit_scenarios"] == [] and any("two-sided" in f for f in bad["flags"])
    assert ev(bid=0.0)["flags"][0].startswith("Zero bid")
    assert any("Quantity" in f for f in ev(quantity=0)["flags"])


def test_concession_is_capped_and_pnl_includes_entry_slippage():
    r = ev(quantity=100, volume=1, open_interest=1, bid=1.0, ask=2.0)
    assert r["exit_scenarios"][1]["bid_concession_pct"] == 65.0
    assert r["exit_scenarios"][2]["bid_concession_pct"] == 85.0
    base = r["exit_scenarios"][0]
    entry = 2.0 * 1.005 * 100 * 100
    assert math.isclose(base["modeled_pnl_usd"], round(base["modeled_exit_usd"] - entry, 2), abs_tol=0.01)


def test_engine_report_carries_liquidity_but_decision_is_unchanged():
    engine, manager, broker, *_ = build(auto_entries=True)
    entry = engine.run_cycle()["entries"][0]
    assert entry["result"] == "FILLED"
    assert entry["liquidity"]["status"] == "SCENARIO_ONLY" and entry["liquidity"]["flags"] == []
