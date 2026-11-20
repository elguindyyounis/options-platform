import importlib.util
import os
import sqlite3
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("migrate_db", Path(__file__).resolve().parent.parent / "deploy/migrate_db.py")
mig = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mig)


def make(path: Path, orders: int, table: str = "orders") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE {table} (id INTEGER)")
    con.executemany(f"INSERT INTO {table} VALUES (?)", [(i,) for i in range(orders)])
    con.commit()
    con.close()
    return path


def test_copies_the_database_with_the_most_orders_and_leaves_originals(tmp_path):
    data, dl = tmp_path / "data", tmp_path / "Downloads"
    a = make(dl / "optoins-platform" / "optplat.db", 5)
    b = make(dl / "OptionsPlatform" / "deep" / "optplat.db", 12)
    make(dl / "alerter" / "state.db", 99)  # the alerter's file name is ignored
    out = mig.migrate(data, [dl])
    assert sqlite3.connect(data / "optplat.db").execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 12
    assert a.exists() and b.exists()  # nothing moved or deleted
    assert any("copied" in m and "12 orders" in m for m in out) and any("left alone" in m and "5 orders" in m for m in out)


def test_never_overwrites_a_database_that_already_has_orders(tmp_path):
    data, dl = tmp_path / "data", tmp_path / "dl"
    keep = make(data / "optplat.db", 3)
    make(dl / "x" / "optplat.db", 50)
    assert "kept" in mig.migrate(data, [dl])[0]
    assert sqlite3.connect(keep).execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 3


def test_empty_fresh_database_is_parked_not_deleted(tmp_path):
    data, dl = tmp_path / "data", tmp_path / "dl"
    make(data / "optplat.db", 0)
    make(dl / "x" / "optplat.db", 7)
    out = mig.migrate(data, [dl])
    assert any("parked" in m for m in out)
    assert list(data.glob("optplat.db.empty-*")) and sqlite3.connect(data / "optplat.db").execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 7


def test_nothing_found_or_unreadable_files_start_fresh(tmp_path):
    dl = tmp_path / "dl"
    (dl / "x").mkdir(parents=True)
    (dl / "x" / "optplat.db").write_text("not a database")
    make(dl / "y" / "optplat.db", 0)  # no orders is not worth copying
    assert mig.migrate(tmp_path / "data", [dl, tmp_path / "missing"]) == ["no earlier database with orders found; starting fresh"]
    assert not (tmp_path / "data" / "optplat.db").exists()
