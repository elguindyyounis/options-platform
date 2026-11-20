"""Replace the installed platform's database with a chosen earlier one. Copies; never edits or deletes the chosen file.

    python deploy/restore_db.py <data-folder> <chosen-optplat.db>

The chosen file must open read-only as SQLite and have an ``orders`` table. The database now in the data folder (if any) is
renamed ``optplat.db.before-restore-<time>`` (with its -wal/-shm files), never removed, so the restore can be undone by hand.
The server must be stopped first (Restore-History.command does that).
"""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

NAME = "optplat.db"


def counts(path: Path) -> dict[str, int] | None:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return {t: int(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]) for t in ("orders", "lane_trades", "equity")}
        finally:
            con.close()
    except sqlite3.Error:
        return None


def restore(data: Path, chosen: Path) -> list[str]:
    c = counts(chosen)
    if c is None:
        raise SystemExit(f"{chosen} is not a readable optplat database. Nothing changed.")
    data.mkdir(parents=True, exist_ok=True)
    target, msgs = data / NAME, []
    if target.resolve() == chosen.resolve():
        raise SystemExit("That is already the installed database. Nothing changed.")
    if target.exists():
        stamp = time.strftime("%Y%m%d%H%M%S")
        for ext in ("", "-wal", "-shm"):
            side = data / (NAME + ext)
            if side.exists():
                side.rename(data / f"{NAME}.before-restore-{stamp}{ext}")
        msgs.append(f"kept the previous installed database as {NAME}.before-restore-{stamp}")
    src = sqlite3.connect(f"file:{chosen}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    msgs.append(f"restored {chosen.name}: {c['orders']} orders, {c['lane_trades']} lane trades, {c['equity']} equity points")
    return msgs


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: restore_db.py <data-folder> <optplat.db>")
    for line in restore(Path(sys.argv[1]), Path(sys.argv[2])):
        print(line)
