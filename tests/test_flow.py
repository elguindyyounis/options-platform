from datetime import timedelta

from helpers import NOW
from optplat.flow import related_themes, scan_flow
from optplat.marketdata import ChainRow, MarketSnapshot
from optplat.models import OptionContract, Right

EXPIRY = NOW.date() + timedelta(days=7)


def snap(symbol, rows, spot=479.59):
    return MarketSnapshot(symbol, spot, (spot,) * 5, tuple(rows), NOW, "test", True)


def row(strike, vol, oi, bid=0.2, ask=0.3, right=Right.PUT):
    return ChainRow(OptionContract("SMH", EXPIRY, right, strike), bid, ask, vol, oi, 0.5)


def test_extreme_put_flow_is_flagged_and_marked_observe_only():
    out = scan_flow(snap("SMH", [row(330.0, 65601, 810), row(400.0, 20, 5000)]))
    assert len(out) == 1
    r = out[0]
    assert r["tier"] == "EXTREME" and r["observe_only"] is True
    assert r["otm_pct"] == 31.2 and r["dte"] == 7
    assert r["volume_oi_ratio"] == 81.0
    assert r["premium_at_quoted_mid_usd"] == round(0.25 * 65601 * 100)
    assert r["ask_side_pct"] is None and r["multi_leg_pct"] is None and r["opening_trade_verified"] is False
    assert r["group"] == "semiconductors" and r["fictional"] is False


def test_normal_or_bad_rows_are_ignored_and_missing_oi_is_labelled():
    assert scan_flow(snap("SMH", [row(330.0, 100, 10), row(330.0, 400, 300), row(330.0, None, None)])) == []
    r = scan_flow(snap("SMH", [row(330.0, 800, None)]))[0]
    assert r["volume_oi_ratio"] is None and any("ratio undefined" in f for f in r["flags"])
    assert scan_flow(snap("SMH", [row(330.0, 800, 0, bid=float("nan"))]))[0]["premium_at_quoted_mid_usd"] is None


def test_related_themes_needs_two_symbols():
    a = scan_flow(snap("SMH", [row(330.0, 65601, 810)]))
    b = scan_flow(snap("MU", [row(410.0, 6181, 931)], spot=760.0))
    assert related_themes(a) == []
    t = related_themes(a + b)
    assert t[0]["group"] == "semiconductors" and t[0]["symbols"] == ["MU", "SMH"]
    assert "not independent" in t[0]["note"]


def test_cycle_report_carries_flow_without_creating_orders():
    from test_engine import build

    engine, manager, *_ = build(auto_entries=False)
    rep = engine.run_cycle()
    assert "flow" in rep and "flow_caveats" in rep and manager.list() == []


def _flow_snapshot():
    rows = [
        row(330.0, 65601, 810, bid=0.24, ask=0.26),          # flagged, 31% OTM
        row(440.0, 400, 600, bid=2.00, ask=2.10),            # nearer, ~8% OTM, liquid
        row(460.0, 900, 5000, bid=7.0, ask=7.2),             # too close to the money for target
    ]
    return snap("SMH", rows)


def test_flow_strategy_requires_movement_evidence_even_for_extreme_turnover():
    from optplat.strategy import FlowFollowStrategy

    s = _flow_snapshot()
    # Unusual turnover alone and five flat closes no longer justify either contract.
    assert FlowFollowStrategy(mode="flagged").propose(s, NOW) == []
    assert FlowFollowStrategy(mode="nearer").propose(s, NOW) == []


def test_flow_strategy_skips_small_premium_short_expiry_and_bad_quotes():
    from optplat.strategy import FlowFollowStrategy

    assert FlowFollowStrategy(min_premium_usd=10_000_000).propose(_flow_snapshot(), NOW) == []
    assert FlowFollowStrategy(min_dte=10).propose(_flow_snapshot(), NOW) == []
    wide = snap("SMH", [row(330.0, 65601, 810, bid=0.05, ask=0.26)])
    assert FlowFollowStrategy().propose(wide, NOW) == []
    assert "unusual-turnover" in FlowFollowStrategy().explain_no_proposal(wide, NOW)
    import pytest
    with pytest.raises(ValueError):
        FlowFollowStrategy(mode="x")


def test_flow_strategy_proposal_goes_through_the_risk_gate_unchanged():
    from optplat.risk import RiskPolicy
    assert RiskPolicy().min_dte == 7 and RiskPolicy().max_spread_pct_of_ask == 15.0  # policy untouched
