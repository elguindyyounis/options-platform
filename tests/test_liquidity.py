from optplat.liquidity import entry_liquidity_review as review
from optplat.strategy import LiquidTrendStrategy
from test_strategy_data import NOW, UP, row, snap

BASE = dict(quantity=1, volume=1000, open_interest=5000, bid=4.90, ask=5.10, limit_price=5.15)


def test_small_order_in_deep_market_has_no_flags_and_orders_scenarios():
    r = review(**BASE)
    assert r["flags"] == []
    labels = [s["scenario"] for s in r["scenarios"]]
    assert labels == ["BASE_BID", "THIN_MARKET", "STRESSED_EXIT"]
    exits = [s["modeled_exit_usd"] for s in r["scenarios"]]
    assert exits == sorted(exits, reverse=True)
    # Even the base case loses the spread: exit at bid against an entry at the limit.
    assert r["scenarios"][0]["modeled_pnl_usd"] < 0
    assert r["entry_cost_usd"] == 515.0


def test_large_order_is_flagged_and_stressed_harder():
    big = review(**{**BASE, "quantity": 600})
    small = review(**BASE)
    assert any("daily volume" in f for f in big["flags"])
    assert any("open interest" in f for f in big["flags"])
    assert big["scenarios"][1]["bid_concession_pct"] > small["scenarios"][1]["bid_concession_pct"]


def test_missing_depth_is_unknown_not_fine():
    r = review(**{**BASE, "volume": None, "open_interest": 0})
    assert r["participation_of_volume"] is None and r["participation_of_open_interest"] is None
    assert len([f for f in r["flags"] if "unknown" in f]) == 2
    assert r["scenarios"][1]["bid_concession_pct"] == 50.0  # worst-case depth assumption


def test_bad_quote_or_quantity_computes_no_scenarios():
    for bad in ({"bid": 6.0}, {"ask": 0}, {"bid": float("nan")}, {"limit_price": None}, {"quantity": 0}):
        r = review(**{**BASE, **bad})
        assert r["scenarios"] == [] and r["flags"]


def test_review_is_labelled_display_only():
    assert "Display only" in review(**BASE)["limits"]


def test_strategy_rationale_carries_quote_for_review_without_changing_proposals():
    p = LiquidTrendStrategy().propose(snap(UP, [row(160)]), NOW)[0]
    assert p.rationale["bid"] == 4.90 and p.rationale["ask"] == 5.10
    assert p.limit_price == 5.15
