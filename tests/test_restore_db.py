import importlib.util
import sqlite3
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("restore_db", Path(__file__).resolve().parent.parent / "deploy/restore_db.py")
rdb = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rdb)


def make(path: Path, orders=0, lanes=0, equity=0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    for t, n in (("orders", orders), ("lane_trades", lanes), ("equity", equity)):
        con.execute(f"CREATE TABLE {t} (id INTEGER)")
        con.executemany(f"INSERT INTO {t} VALUES (?)", [(i,) for i in range(n)])
    con.commit()
    con.close()
    return path


def rows(path: Path, table: str) -> int:
    return sqlite3.connect(path).execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_restore_copies_and_keeps_both_old_files(tmp_path):
    data = tmp_path / "data"
    make(data / "optplat.db", orders=1)
    chosen = make(tmp_path / "old" / "optplat.db", orders=6, lanes=39, equity=276)
    out = rdb.restore(data, chosen)
    assert rows(data / "optplat.db", "lane_trades") == 39 and "6 orders, 39 lane trades, 276 equity points" in out[-1]
    assert rows(chosen, "orders") == 6  # the chosen file is untouched
    parked = list(data.glob("optplat.db.before-restore-*"))
    assert len(parked) == 1 and rows(parked[0], "orders") == 1  # the previous one is kept, not removed


def test_restore_refuses_bad_or_same_file(tmp_path):
    data = tmp_path / "data"
    bad = tmp_path / "bad.db"
    bad.write_text("not a database")
    with pytest.raises(SystemExit):
        rdb.restore(data, bad)
    same = make(data / "optplat.db", orders=2)
    with pytest.raises(SystemExit):
        rdb.restore(data, same)
    assert rows(same, "orders") == 2


def test_installer_scripts_parse():
    import subprocess
    assert subprocess.run(["bash", "-n", str(Path(__file__).resolve().parent.parent / "Restore-History.command")]).returncode == 0
