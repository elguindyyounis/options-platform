"""Find an earlier paper database and COPY it into the managed install's data folder. Never moves, edits or deletes anything.

    python deploy/migrate_db.py <data-folder> [search-folder ...]

Looks for files named ``optplat.db`` (the platform's own database; the alerter's ``state.db`` has a different layout and is
ignored) under the given folders, to two levels deep. A candidate must open read-only as SQLite and have an ``orders``
table. The one with the most orders wins (ties: newest). It is copied to ``<data-folder>/optplat.db`` when that file does
not exist or holds no orders; an empty one is renamed ``optplat.db.empty-<time>``, never removed. Other candidates are
only listed. Prints what it did, one line per action.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import time
from pathlib import Path

NAME = "optplat.db"


def orders_in(path: Path) -> int | None:
    """Number of orders, or None when the file is not a readable platform database."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return int(con.execute("SELECT COUNT(*) FROM orders").fetchone()[0])
        finally:
            con.close()
    except sqlite3.Error:
        return None


def candidates(folders: list[Path]) -> list[Path]:
    found: dict[Path, None] = {}
    for base in folders:
        if not base.is_dir():
            continue
        for pattern in (NAME, f"*/{NAME}", f"*/*/{NAME}"):
            for p in base.glob(pattern):
                if p.is_file() and not p.is_symlink():
                    found[p.resolve()] = None
    return list(found)


def migrate(data: Path, folders: list[Path]) -> list[str]:
    msgs: list[str] = []
    target = data / NAME
    have = orders_in(target) if target.exists() else None
    if have:
        return [f"kept: {target} already has {have} orders; nothing copied"]
    scored = [(n, p.stat().st_mtime, p) for p in candidates([f for f in folders if f.resolve() != data.resolve()])
              if (n := orders_in(p)) is not None]
    scored = [s for s in scored if s[0] > 0]
    if not scored:
        return ["no earlier database with orders found; starting fresh"]
    scored.sort(key=lambda s: (-s[0], -s[1]))
    best = scored[0]
    if target.exists():
        parked = data / f"{NAME}.empty-{time.strftime('%Y%m%d%H%M%S')}"
        target.rename(parked)
        for ext in ("-wal", "-shm"):
            side = data / (NAME + ext)
            if side.exists():
                side.rename(data / (parked.name + ext))
        msgs.append(f"parked the empty database as {parked.name}")
    data.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{best[2]}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)  # a consistent copy even if the old copy was left running
    finally:
        dst.close()
        src.close()
    msgs.append(f"copied {best[2]} ({best[0]} orders) to {target}")
    msgs += [f"also found, left alone: {p} ({n} orders)" for n, _, p in scored[1:]]
    return msgs


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit("usage: migrate_db.py <data-folder> <search-folder> [...]")
    for line in migrate(Path(sys.argv[1]), [Path(a) for a in sys.argv[2:]]):
        print(line)
