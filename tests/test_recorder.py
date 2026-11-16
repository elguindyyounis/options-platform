from datetime import datetime, timedelta, timezone

from helpers import NOW
from optplat.marketdata import snapshot_from_dict, snapshot_to_dict
from test_engine import SATURDAY, build, snapshot


def test_snapshot_round_trips_through_json_exactly():
    snap = snapshot()
    again = snapshot_from_dict(snapshot_to_dict(snap))
    assert again == snap


def test_every_symbol_snapshot_seen_in_a_cycle_is_recorded_once():
    engine, manager, broker, provider, clock = build(symbols=("AAA", "BBB"), auto_entries=True)
    report = engine.run_cycle()
    rows = manager.store.list_snapshots()
    assert sorted(r["symbol"] for r in rows) == ["AAA", "BBB"]  # one per symbol, even though several phases read it
    assert report["snapshots_recorded"] == 2
    first = rows[0]
    assert first["source"] == "test" and first["timestamp_verified"] is True and first["fictional"] is False
    assert first["recorded_at"] == NOW.isoformat()
    assert snapshot_from_dict(first["payload"]) == snapshot(first["symbol"])


def test_each_cycle_adds_a_new_observation_in_time_order():
    engine, manager, _, provider, clock = build()
    engine.run_cycle()
    clock.now = NOW + timedelta(seconds=60)
    provider.set_snapshot(snapshot(bid=5.0, ask=5.2))
    engine.run_cycle()
    rows = manager.store.list_snapshots(symbol="AAA")
    assert [r["recorded_at"] for r in rows] == [NOW.isoformat(), (NOW + timedelta(seconds=60)).isoformat()]


def test_fictional_data_is_labelled_and_kept_out_of_default_queries():
    engine, manager, _, provider, _ = build()
    provider.fictional = True
    engine.run_cycle()
    store = manager.store
    assert store.list_snapshots() == []
    assert len(store.list_snapshots(include_fictional=True)) == 1
    assert store.snapshot_stats()["fictional"] == 1 and store.snapshot_stats()["real"] == 0


def test_recording_can_be_switched_off():
    engine, manager, *_ = build(record_snapshots=False)
    report = engine.run_cycle()
    assert report["snapshots_recorded"] == 0 and manager.store.snapshot_stats()["total"] == 0


def test_recording_also_happens_when_the_market_is_closed():
    engine, manager, _, _, clock = build()
    clock.now = SATURDAY
    engine.run_cycle()
    assert manager.store.snapshot_stats()["total"] == 1


def test_a_recording_failure_is_reported_but_does_not_stop_the_cycle(monkeypatch):
    engine, manager, *_ = build(auto_entries=True)

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(manager.store, "record_snapshot", boom)
    report = engine.run_cycle()
    assert any(e.startswith("record AAA") for e in report["errors"])
    assert report["entries"][0]["result"] == "FILLED"  # trading logic unaffected


def test_a_failed_data_fetch_records_nothing_and_never_invents_a_row():
    engine, manager, _, provider, _ = build(symbols=("AAA",))
    engine.set_config({"watchlist": ["ZZZ"]})  # no snapshot set for ZZZ: the provider raises
    report = engine.run_cycle()
    assert manager.store.snapshot_stats()["total"] == 0
    assert any("data ZZZ" in e for e in report["errors"])


def test_old_snapshots_are_pruned_by_retention_at_most_hourly():
    engine, manager, _, provider, clock = build(snapshot_retention_days=1)
    store = manager.store
    engine.run_cycle()  # recorded at NOW
    clock.now = NOW + timedelta(days=2)
    provider.set_snapshot(snapshot())
    engine.run_cycle()  # prune cuts anything older than 1 day, then records the new one
    assert [r["recorded_at"] for r in store.list_snapshots()] == [(NOW + timedelta(days=2)).isoformat()]
    # throttled: an old row inserted now survives a cycle 10 minutes later, then goes after an hour
    store.record_snapshot("AAA", NOW, NOW, "test", False, True, snapshot_to_dict(snapshot()))
    clock.now = NOW + timedelta(days=2, minutes=10)
    engine.run_cycle()
    assert len(store.list_snapshots()) == 3
    clock.now = NOW + timedelta(days=2, minutes=70)
    engine.run_cycle()
    assert all(r["recorded_at"] >= (NOW + timedelta(days=1, minutes=70)).isoformat() for r in store.list_snapshots())


def test_retention_must_be_a_sane_number_of_days():
    import pytest

    engine, *_ = build()
    for bad in (0, -5, 4000):
        with pytest.raises(ValueError, match="snapshot_retention_days"):
            engine.set_config({"snapshot_retention_days": bad})
    with pytest.raises(ValueError, match="wrong type"):
        engine.set_config({"record_snapshots": "yes"})


def test_status_reports_what_has_been_recorded():
    engine, *_ = build()
    engine.run_cycle()
    rec = engine.status()["recorder"]
    assert rec["total"] == 1 and rec["real"] == 1 and rec["newest"] == NOW.isoformat()


def test_list_snapshots_filters_by_symbol_and_time_window():
    engine, manager, _, provider, clock = build(symbols=("AAA", "BBB"))
    engine.run_cycle()
    clock.now = NOW + timedelta(seconds=60)
    engine.run_cycle()
    store = manager.store
    assert len(store.list_snapshots(symbol="AAA")) == 2
    assert len(store.list_snapshots(since=NOW + timedelta(seconds=30))) == 2
    assert len(store.list_snapshots(until=NOW + timedelta(seconds=30))) == 2
    assert len(store.list_snapshots(limit=1)) == 1
