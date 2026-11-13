import math

from optplat.stress import MAX_CONCESSION_PCT, exit_stress, extra_concession_pct

BASE = dict(entry_fill=2.0, bid=2.0, ask=2.1, quantity=1, multiplier=100)


def by_name(res):
    return {s["scenario"]: s for s in res["scenarios"]}


def test_scenarios_are_ordered_worst_last():
    r = by_name(exit_stress(**BASE, volume=1000, open_interest=5000))
    assert r["SIM_ASSUMPTION"]["modeled_pnl_usd"] >= r["THIN_MARKET"]["modeled_pnl_usd"]
    assert r["THIN_MARKET"]["modeled_pnl_usd"] > r["STRESSED_EXIT"]["modeled_pnl_usd"]


def test_sim_assumption_matches_flat_slippage():
    r = by_name(exit_stress(**BASE, volume=1000, open_interest=5000, slippage_pct=0.5))
    assert r["SIM_ASSUMPTION"]["modeled_exit_usd"] == round(2.0 * 0.995 * 100, 2)


def test_unknown_depth_is_harsher_than_deep_market_and_flagged():
    deep = exit_stress(**BASE, volume=10_000, open_interest=50_000)
    unknown = exit_stress(**BASE)
    assert deep["depth_known"] and not unknown["depth_known"]
    assert by_name(unknown)["THIN_MARKET"]["modeled_pnl_usd"] < by_name(deep)["THIN_MARKET"]["modeled_pnl_usd"]


def test_invalid_depth_values_treated_as_unknown():
    for bad in (float("nan"), float("inf"), -5, 0, True, "x"):
        r = exit_stress(**BASE, volume=bad, open_interest=bad)
        assert r is not None and not r["depth_known"]


def test_wide_spread_and_size_increase_concession():
    assert extra_concession_pct(30, 10, 20, 100) > extra_concession_pct(2, 1, 5000, 50000)
    assert extra_concession_pct(2, 1, 5000, 50000) < 0.1


def test_concession_capped_and_proceeds_never_negative():
    r = exit_stress(**BASE, slippage_pct=90)
    for s in r["scenarios"]:
        assert s["bid_concession_pct"] <= MAX_CONCESSION_PCT
        assert s["modeled_exit_usd"] >= 0


def test_unusable_inputs_return_none():
    for kw in (
        dict(entry_fill=0), dict(entry_fill=float("nan")), dict(bid=-1), dict(bid=3.0),
        dict(ask=0), dict(quantity=0), dict(multiplier=0), dict(slippage_pct=float("inf")),
    ):
        assert exit_stress(**{**BASE, **kw}) is None


def test_zero_bid_gives_total_loss_scenarios():
    r = exit_stress(**{**BASE, "bid": 0.0})
    assert all(s["modeled_exit_usd"] == 0 and s["premium_return_pct"] == -100.0 for s in r["scenarios"])


def test_output_is_finite_and_labelled_hypothetical():
    r = exit_stress(**BASE)
    assert "not" in r["warning"].lower()
    assert all(math.isfinite(s["modeled_pnl_usd"]) for s in r["scenarios"])
