import math
from dataclasses import replace
from datetime import timedelta

import pytest

from helpers import NOW
from optplat.dataquality import (MAX_SNAPSHOT_AGE_S, check_snapshot, frozen_issue, quote_fingerprint)
from optplat.marketdata import ChainRow
from optplat.models import OptionContract, Right
from test_engine import EXPIRY, UP, build, snapshot


def row(strike=160.0, bid=4.9, ask=5.1, **kw):
    return ChainRow(OptionContract("AAA", EXPIRY, Right.CALL, strike), bid, ask, kw.get("volume", 200),
                    kw.get("open_interest", 2000), kw.get("iv", 0.3))


def snap_with(*rows, **kw):
    return replace(snapshot(), rows=tuple(rows), **kw)


def kinds(result):
    return {i.kind: i for i in result.issues}


def test_a_clean_snapshot_passes_through_unchanged_and_is_the_same_object():
    s = snapshot()
    result = check_snapshot(s, NOW)
    assert result.snapshot is s and result.issues == () and not result.rejected


@pytest.mark.parametrize("bid,ask,kind", [
    (5.2, 5.1, "CROSSED_QUOTE"), (0.0, 0.0, "ZERO_ASK"), (-1.0, 5.1, "NONFINITE_QUOTE"),
    (math.nan, 5.1, "NONFINITE_QUOTE"), (4.9, math.inf, "NONFINITE_QUOTE"),
])
def test_bad_rows_are_dropped_and_good_rows_kept(bid, ask, kind):
    result = check_snapshot(snap_with(row(160, bid, ask), row(165)), NOW)
    assert [r.contract.strike for r in result.snapshot.rows] == [165.0]
    assert kinds(result)[kind].severity == "drop" and kinds(result)[kind].count == 1


def test_expired_and_duplicate_contracts_are_dropped():
    expired = ChainRow(OptionContract("AAA", NOW.date() - timedelta(days=1), Right.CALL, 160.0), 1.0, 1.1)
    result = check_snapshot(snap_with(row(160), row(160), expired, row(170)), NOW)
    assert [r.contract.strike for r in result.snapshot.rows] == [160.0, 170.0]
    assert kinds(result)["DUPLICATE_CONTRACT"].count == 1 and kinds(result)["EXPIRED_CONTRACT"].count == 1


def test_implausible_side_data_is_removed_not_corrected():
    result = check_snapshot(snap_with(row(iv=9.0, volume=-5, open_interest=-1)), NOW)
    r = result.snapshot.rows[0]
    assert r.iv is None and r.volume is None and r.open_interest is None and (r.bid, r.ask) == (4.9, 5.1)
    assert {"IMPLAUSIBLE_IV", "NEGATIVE_VOLUME", "NEGATIVE_OPEN_INTEREST"} <= set(kinds(result))
    assert all(i.severity == "warn" for i in result.issues)
    assert check_snapshot(snap_with(row(iv=0.0)), NOW).snapshot.rows[0].iv is None  # zero vol is not a real value


def test_a_snapshot_with_no_usable_rows_is_rejected():
    result = check_snapshot(snap_with(row(bid=6, ask=5), row(165, 0, 0)), NOW)
    assert result.rejected and kinds(result)["EMPTY_CHAIN"].severity == "reject"


def test_stale_future_and_bad_price_snapshots_are_rejected():
    assert kinds(check_snapshot(snapshot(), NOW + timedelta(seconds=MAX_SNAPSHOT_AGE_S + 1)))["STALE_SNAPSHOT"]
    assert check_snapshot(snapshot(), NOW + timedelta(seconds=MAX_SNAPSHOT_AGE_S)).snapshot is not None  # at the limit
    assert kinds(check_snapshot(snapshot(), NOW - timedelta(seconds=60)))["FUTURE_TIMESTAMP"]
    assert check_snapshot(replace(snapshot(), underlying=0.0), NOW).rejected
    assert check_snapshot(replace(snapshot(), underlying=math.nan), NOW).rejected
    assert kinds(check_snapshot(replace(snapshot(), closes=UP[:-1] + (math.nan,)), NOW))["BAD_HISTORY"]
    assert kinds(check_snapshot(replace(snapshot(), closes=UP[:-1] + (0.0,)), NOW))["BAD_HISTORY"]


def test_a_spot_far_from_the_last_close_is_flagged_but_kept():
    result = check_snapshot(replace(snapshot(), underlying=UP[-1] * 1.5), NOW)
    assert not result.rejected and kinds(result)["UNDERLYING_GAP"].severity == "warn"


def test_frozen_quote_detection_only_while_the_market_is_open():
    assert frozen_issue(2, True) is None and frozen_issue(3, True).kind == "FROZEN_QUOTES"
    assert frozen_issue(50, False) is None
    assert quote_fingerprint(snapshot()) == quote_fingerprint(snapshot())
    assert quote_fingerprint(snapshot()) != quote_fingerprint(snapshot(bid=4.8))


# ------------------------------------------------------------ engine integration
def test_crossed_rows_never_reach_the_strategy_and_the_issue_is_logged():
    engine, manager, broker, provider, clock = build(auto_entries=True)
    good = snapshot("AAA", bid=4.9, ask=5.1, strike=160.0)
    bad = ChainRow(OptionContract("AAA", EXPIRY, Right.CALL, 150.0), 9.0, 8.0, 500, 5000, 0.3)  # crossed
    provider.set_snapshot(replace(good, rows=(bad,) + good.rows))
    report = engine.run_cycle()
    assert [i["kind"] for i in report["data_quality"]] == ["CROSSED_QUOTE"]
    assert report["entries"][0]["result"] == "FILLED" and report["entries"][0]["contract"].endswith("00160000")
    summary = manager.store.data_issue_summary(NOW - timedelta(hours=1))
    assert summary["CROSSED_QUOTE"]["events"] == 1 and summary["CROSSED_QUOTE"]["severity"] == "drop"


def test_a_rejected_snapshot_is_treated_like_a_failed_fetch_and_fails_closed():
    engine, manager, broker, provider, clock = build(auto_entries=True)
    provider.set_snapshot(replace(snapshot(), underlying=0.0))
    report = engine.run_cycle()
    assert any("rejected (BAD_UNDERLYING" in e for e in report["errors"])
    assert broker.get_positions() == [] and manager.list() == []  # nothing was traded on bad data


def test_a_rejected_snapshot_gives_no_new_entries_for_that_symbol_but_a_held_position_is_still_marked():
    engine, manager, broker, provider, clock = build(auto_entries=True, reentry_cooldown_s=0, max_new_per_cycle=5)
    engine.run_cycle()
    assert len(broker.get_positions()) == 1
    provider.set_snapshot(replace(snapshot(), underlying=math.nan))  # unusable picture of the underlying
    clock.now = clock.now + timedelta(seconds=2000)
    report = engine.run_cycle()
    assert any("rejected (BAD_UNDERLYING" in e for e in report["errors"])
    assert len(broker.get_positions()) == 1 and all(e["result"] != "FILLED" for e in report["entries"])
    assert report["exits"][0]["action"] == "HOLD"  # the position still has its own valid bid, so it is not blindly sold


def test_the_raw_snapshot_is_recorded_even_when_it_is_rejected():
    engine, manager, *_ , provider, clock = build()
    provider.set_snapshot(replace(snapshot(), underlying=0.0))
    engine.run_cycle()
    rows = manager.store.list_snapshots()
    assert len(rows) == 1 and rows[0]["payload"]["underlying"] == 0.0  # evidence kept; the gate decides at use time


def test_frozen_quotes_are_flagged_after_three_unchanged_cycles_while_open():
    engine, manager, broker, provider, clock = build()
    seen = []
    for i in range(5):
        clock.now = NOW + timedelta(seconds=60 * i)
        seen.append([x["kind"] for x in engine.run_cycle()["data_quality"]])
    assert seen[:3] == [[], [], []] and seen[3] == ["FROZEN_QUOTES"] and seen[4] == ["FROZEN_QUOTES"]
    assert manager.store.data_issue_summary(NOW)["FROZEN_QUOTES"]["events"] == 2


def test_status_summarises_the_last_24_hours_of_data_issues():
    engine, manager, broker, provider, clock = build()
    provider.set_snapshot(replace(snapshot(), underlying=0.0))
    engine.run_cycle()
    dq = engine.status()["data_quality"]
    assert dq["window_hours"] == 24 and dq["issues"]["BAD_UNDERLYING"]["severity"] == "reject"
    clock.now = NOW + timedelta(hours=25)
    assert engine.status()["data_quality"]["issues"] == {}  # old issues age out of the window


def test_data_issues_are_pruned_with_the_snapshot_retention_window():
    engine, manager, broker, provider, clock = build(snapshot_retention_days=1)
    provider.set_snapshot(replace(snapshot(), underlying=0.0))
    engine.run_cycle()
    provider.set_snapshot(snapshot())
    clock.now = NOW + timedelta(days=3)
    engine.run_cycle()
    assert manager.store.data_issue_summary(NOW - timedelta(days=1)).get("BAD_UNDERLYING") is None


def test_replay_applies_the_same_gate_so_decisions_match_live():
    from optplat.marketdata import snapshot_to_dict
    from optplat.replay import run_replay

    bad = replace(snapshot(), underlying=0.0, as_of=NOW)
    rows = [{"id": 1, "symbol": "AAA", "recorded_at": NOW.isoformat(), "fictional": False,
             "payload": snapshot_to_dict(bad)}]
    result = run_replay(rows, config={"auto_entries": True})
    assert any("rejected (BAD_UNDERLYING" in e for e in result.cycles[0]["errors"]) and result.report["closed_trades"] == 0
