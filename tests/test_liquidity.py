import pytest

from test_engine import build
from optplat.liquidity import participation_tags


def test_small_order_is_within_ten_percent():
    t = participation_tags(5, 100, 1000)
    assert t["fill_realism"] == "WITHIN_10PCT" and t["flags"] == []
    assert t["pct_of_volume"] == 5.0 and t["pct_of_open_interest"] == 0.5


def test_oversized_order_is_flagged():
    t = participation_tags(30, 200, 1000)
    assert t["fill_realism"] == "QUESTIONABLE"
    assert any("volume" in f for f in t["flags"])
    assert not any("open_interest" in f and "%" in f for f in t["flags"])


def test_exactly_ten_percent_is_not_flagged():
    assert participation_tags(10, 100, 100)["fill_realism"] == "WITHIN_10PCT"
    assert participation_tags(11, 100, 1000)["fill_realism"] == "QUESTIONABLE"


@pytest.mark.parametrize("vol,oi", [(None, 500), (0, 500), (100, None), ("x", 100), (float("nan"), 100), (-5, 100)])
def test_unknown_volume_or_oi_fails_closed(vol, oi):
    t = participation_tags(1, vol, oi)
    assert t["fill_realism"] == "QUESTIONABLE" and t["flags"]


def test_engine_report_carries_tags_without_changing_the_order():
    engine, manager, broker, provider, clock = build(auto_entries=True)
    report = engine.run_cycle()
    entry = report["entries"][0]
    assert entry["liquidity"]["status"] == "SCENARIO_ONLY"
    assert entry["liquidity"]["quantity"] == entry["quantity"]
    assert "liquidity" not in entry["rationale"]
