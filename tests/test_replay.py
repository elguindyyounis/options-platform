from dataclasses import replace
from datetime import timedelta

import pytest

from helpers import NOW
from optplat.marketdata import snapshot_to_dict
from optplat.replay import ReplayClock, ReplayDataProvider, run_replay
from optplat.risk import RiskPolicy
from test_engine import SATURDAY, build, snapshot


def row(symbol="AAA", at=NOW, bid=4.90, ask=5.10, fictional=False, verified=True, rid=1):
    snap = replace(snapshot(symbol, bid=bid, ask=ask), as_of=at, timestamp_verified=verified, fictional=fictional)
    return {
        "id": rid,
        "symbol": symbol,
        "recorded_at": at.isoformat(),
        "fictional": fictional,
        "payload": snapshot_to_dict(snap),
    }


def two_step_rows():
    return [row(at=NOW, bid=4.90, ask=5.10, rid=1), row(at=NOW + timedelta(seconds=60), bid=7.5, ask=7.7, rid=2)]


# ------------------------------------------------------------ provider
def test_provider_never_looks_ahead_and_serves_the_latest_known_snapshot():
    clock = ReplayClock(NOW - timedelta(seconds=1))
    provider = ReplayDataProvider(two_step_rows(), clock)
    with pytest.raises(RuntimeError, match="No recorded snapshot"):
        provider.snapshot("AAA")  # nothing recorded yet at this time
    clock.now = NOW
    assert provider.snapshot("AAA").rows[0].bid == 4.90
    clock.now = NOW + timedelta(seconds=59)
    assert provider.snapshot("AAA").rows[0].bid == 4.90  # the later snapshot is still in the future
    clock.now = NOW + timedelta(seconds=60)
    assert provider.snapshot("AAA").rows[0].bid == 7.5


def test_steps_are_sorted_and_distinct_even_for_unsorted_input_and_several_symbols():
    rows = [row("BBB", NOW + timedelta(seconds=60), rid=3), row("AAA", NOW, rid=1), row("BBB", NOW, rid=2),
            row("AAA", NOW + timedelta(seconds=60), rid=4)]
    provider = ReplayDataProvider(rows, ReplayClock(NOW))
    assert provider.steps() == [NOW, NOW + timedelta(seconds=60)]
    assert provider.symbols() == ["AAA", "BBB"]


def test_quotes_for_held_contracts_come_from_the_latest_known_snapshot_only():
    clock = ReplayClock(NOW)
    provider = ReplayDataProvider(two_step_rows(), clock)
    contract = provider.snapshot("AAA").rows[0].contract
    assert provider.quotes_for([contract])[0].bid == 4.90
    clock.now = NOW + timedelta(seconds=60)
    assert provider.quotes_for([contract])[0].bid == 7.5
    assert provider.quotes_for([]) == []


def test_real_and_fictional_rows_are_never_mixed_and_fictional_is_carried_through():
    with pytest.raises(ValueError, match="real and fictional"):
        ReplayDataProvider([row(rid=1), row(at=NOW + timedelta(seconds=1), fictional=True, rid=2)], ReplayClock(NOW))
    assert ReplayDataProvider([row(fictional=True)], ReplayClock(NOW)).fictional is True
    assert ReplayDataProvider([row()], ReplayClock(NOW)).fictional is False


def test_nothing_to_replay_is_an_error_not_an_empty_success():
    with pytest.raises(ValueError, match="No recorded snapshots"):
        ReplayDataProvider([], ReplayClock(NOW))
    with pytest.raises(ValueError):
        run_replay([])


# ------------------------------------------------------------ replay run
def test_replay_drives_the_real_engine_entry_then_take_profit_exit():
    result = run_replay(two_step_rows(), config={"auto_entries": True})
    assert result.steps == 2
    assert result.trace[0][1][0][0] == "entry" and result.trace[0][1][0][2] == "FILLED"
    exit_item = result.cycles[1]["exits"][0]
    assert (exit_item["action"], exit_item["trigger"], exit_item["result"]) == ("EXIT", "take_profit", "FILLED")
    assert result.report["realized_pnl"] == 233.0  # same numbers as the live-engine test: ask 5.10 in, bid 7.50 out
    assert result.report["open"] == []


def test_entries_are_off_unless_the_caller_turns_them_on():
    result = run_replay(two_step_rows())
    assert all(items == [] for _, items in result.trace) and result.report["closed_trades"] == 0


def test_a_replay_is_reproducible():
    first = run_replay(two_step_rows(), config={"auto_entries": True})
    second = run_replay(two_step_rows(), config={"auto_entries": True})
    assert first.fingerprint() == second.fingerprint()
    other = run_replay([row(at=NOW, rid=1), row(at=NOW + timedelta(seconds=60), bid=4.0, ask=4.2, rid=2)],
                       config={"auto_entries": True})
    assert other.fingerprint() != first.fingerprint()  # the fingerprint does depend on what happened


def test_the_strict_quote_policy_still_applies_unless_the_caller_opts_out_explicitly():
    unverified = [row(verified=False, rid=1), row(at=NOW + timedelta(seconds=60), verified=False, bid=7.5, ask=7.7, rid=2)]
    strict = run_replay(unverified, config={"auto_entries": True})
    assert strict.report["closed_trades"] == 0 and strict.trace[0][1][0][2] != "FILLED"
    relaxed = run_replay(unverified, config={"auto_entries": True}, policy=RiskPolicy(require_verified_quote_time=False))
    assert relaxed.trace[0][1][0][2] == "FILLED"  # only with the same explicit opt-in used live


def test_market_hours_still_apply_to_recorded_real_data():
    result = run_replay([row(at=SATURDAY, rid=1)], config={"auto_entries": True})
    assert result.cycles[0]["trading_allowed"] is False and result.report["closed_trades"] == 0
    assert "Market closed" in result.cycles[0]["entries_note"]


def test_replay_does_not_record_snapshots_again():
    result = run_replay(two_step_rows(), config={"auto_entries": True, "record_snapshots": True})
    assert all(c["snapshots_recorded"] == 0 for c in result.cycles)  # the replay can never inflate the recorder


# ------------------------------------------------------------ record -> replay end to end
def test_recorded_live_cycles_can_be_replayed_and_give_the_same_decisions():
    engine, manager, broker, provider, clock = build(auto_entries=True)
    engine.run_cycle()  # records NOW, opens a position
    clock.now = NOW + timedelta(seconds=60)
    provider.set_snapshot(snapshot(bid=7.5, ask=7.7))
    engine.run_cycle()  # records +60s, take-profit exit
    live_pnl = manager.report()["realized_pnl"]

    rows = manager.store.list_snapshots()
    assert len(rows) == 2
    replayed = run_replay(rows, config={"auto_entries": True})
    assert replayed.report["realized_pnl"] == live_pnl == 233.0
