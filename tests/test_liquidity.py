import pytest

from optplat.liquidity import fill_realism

from test_engine import build


def test_small_order_against_deep_market_has_no_tags():
    r = fill_realism(1, 200, 2000)
    assert r["tags"] == [] and r["sim_fill_may_be_optimistic"] is False


def test_order_above_ten_percent_of_volume_or_oi_is_tagged():
    assert "EXCEEDS_10PCT_OF_VOLUME" in fill_realism(30, 200, 100000)["tags"]
    assert "EXCEEDS_10PCT_OF_OPEN_INTEREST" in fill_realism(30, 100000, 200)["tags"]
    assert fill_realism(20, 200, 200)["tags"] == []  # exactly 10% is not flagged


@pytest.mark.parametrize("bad", [None, "5", -1, float("nan"), float("inf"), True])
def test_missing_or_bad_volume_and_oi_are_unverified_not_fine(bad):
    r = fill_realism(1, bad, bad)
    assert {"VOLUME_UNVERIFIED", "OI_UNVERIFIED"} <= set(r["tags"])
    assert r["sim_fill_may_be_optimistic"] is True


def test_bad_quantity_is_tagged():
    assert "QUANTITY_UNKNOWN" in fill_realism(0, 200, 2000)["tags"]


def test_engine_entry_report_carries_the_label_without_changing_the_order():
    engine, manager, broker, *_ = build(auto_entries=True)
    entry = engine.run_cycle()["entries"][0]
    assert entry["result"] == "FILLED" and entry["quantity"] == 1
    assert entry["fill_realism"]["tags"] == [] and entry["fill_realism"]["volume"] == 200
