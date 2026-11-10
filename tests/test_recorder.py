from datetime import timedelta

import pytest

from helpers import NOW
from optplat.engine import EngineConfig
from optplat.store import Store
from test_engine import EXPIRY, build, contract, snapshot  # noqa: F401


def test_recording_defaults():
    cfg = EngineConfig()
    assert cfg.record_market_data is True and cfg.record_retention_days == 90
    assert cfg.auto_entries is False  # recorder change must not touch safety defaults


def test_cycle_records_snapshot_and_rows():
    engine, manager, *_ = build()
    engine.run_cycle()
    store = manager.store
    assert store.recorder_counts() == {"snapshots": 1, "quotes": 1}
    rec = store.recorded_snapshots("AAA")[0]
    assert rec["source"] == "test" and rec["timestamp_verified"] is True and rec["fictional"] is False
    assert rec["recorded_at"] == NOW.isoformat() and rec["as_of"] == NOW.isoformat()
    assert rec["closes"][-1] == 159.0
    row = rec["rows"][0]
    assert (row["bid"], row["ask"], row["strike"], row["right"]) == (4.90, 5.10, 160.0, "C")
    assert row["open_interest"] == 2000 and row["iv"] == 0.3


def test_each_cycle_appends_in_time_order():
    engine, manager, _, _, clock = build()
    engine.run_cycle()
    clock.now = NOW + timedelta(minutes=5)
    engine.run_cycle()
    snaps = manager.store.recorded_snapshots("AAA")
    assert [s["recorded_at"] for s in snaps] == [NOW.isoformat(), (NOW + timedelta(minutes=5)).isoformat()]


def test_recording_can_be_disabled():
    engine, manager, *_ = build(record_market_data=False)
    engine.run_cycle()
    assert manager.store.recorder_counts() == {"snapshots": 0, "quotes": 0}


def test_fictional_flag_is_stored():
    store = Store(":memory:")
    from dataclasses import replace

    store.record_snapshot(replace(snapshot(), fictional=True), recorded_at=NOW)
    assert store.recorded_snapshots()[0]["fictional"] is True


def test_recorder_failure_does_not_stop_cycle(monkeypatch):
    engine, manager, *_ = build()

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(manager.store, "record_snapshot", boom)
    report = engine.run_cycle()
    assert any(e.startswith("recorder AAA") for e in report["errors"])
    assert report["data_source"]  # cycle still finished
    assert manager.store.get_state("last_cycle")


def test_failed_insert_rolls_back_snapshot_header():
    store = Store(":memory:")
    bad = snapshot()
    object.__setattr__(bad, "rows", (object(),))  # row access will raise mid-transaction
    with pytest.raises(Exception):
        store.record_snapshot(bad, recorded_at=NOW)
    assert store.recorder_counts() == {"snapshots": 0, "quotes": 0}


def test_standalone_quotes_recorded():
    from helpers import make_quote

    store = Store(":memory:")
    assert store.record_quotes([make_quote()], fictional=False, recorded_at=NOW) == 1
    assert store.record_quotes([], fictional=False) == 0
    assert store.recorder_counts() == {"snapshots": 0, "quotes": 1}


def test_retention_purges_old_rows_only():
    store = Store(":memory:")
    store.record_snapshot(snapshot(), recorded_at=NOW - timedelta(days=100))
    store.record_snapshot(snapshot(), recorded_at=NOW - timedelta(days=1))
    assert store.purge_market_data(0, now=NOW) == 0  # 0 = keep forever
    assert store.recorder_counts() == {"snapshots": 2, "quotes": 2}
    assert store.purge_market_data(90, now=NOW) == 2
    assert store.recorder_counts() == {"snapshots": 1, "quotes": 1}


def test_cycle_applies_retention():
    engine, manager, *_ = build(record_retention_days=30)
    manager.store.record_snapshot(snapshot(), recorded_at=NOW - timedelta(days=60))
    engine.run_cycle()
    assert [s["recorded_at"] for s in manager.store.recorded_snapshots()] == [NOW.isoformat()]


@pytest.mark.parametrize("bad", [-1, 3651])
def test_retention_validated(bad):
    engine, *_ = build()
    with pytest.raises(ValueError, match="record_retention_days"):
        engine.set_config({"record_retention_days": bad})
