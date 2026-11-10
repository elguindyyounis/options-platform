"""SQLite persistence for orders, an append-only audit log and small key/value state."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .models import Order, OrderState, TERMINAL_STATES, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    idem_key TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    order_id TEXT,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS state (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    as_of TEXT NOT NULL,
    source TEXT NOT NULL,
    fictional INTEGER NOT NULL,
    timestamp_verified INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS data_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    count INTEGER NOT NULL,
    detail TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_data_issues_ts ON data_issues(ts);
CREATE INDEX IF NOT EXISTS idx_snapshots_symbol_time ON snapshots(symbol, recorded_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_recorded ON snapshots(recorded_at);
"""


class Store:
    def __init__(self, path: str = ":memory:", *, read_only: bool = False) -> None:
        if read_only:
            # For analysis tools: the file cannot be modified through this handle, and no tables are created.
            uri = Path(path).resolve().as_uri() + "?mode=ro"
            self._db = sqlite3.connect(uri, uri=True, check_same_thread=False)
        else:
            self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        if not read_only:
            with self._lock:
                self._db.executescript(SCHEMA)
                self._db.commit()

    # ---- orders -------------------------------------------------------
    def insert_order(self, order: Order) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO orders (id, idem_key, state, payload, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (
                    order.id,
                    order.intent.idempotency_key,
                    order.state.value,
                    json.dumps(order.to_dict()),
                    order.created_at.isoformat(),
                    order.updated_at.isoformat(),
                ),
            )
            self._db.commit()

    def save_order(self, order: Order) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE orders SET state=?, payload=?, updated_at=? WHERE id=?",
                (order.state.value, json.dumps(order.to_dict()), order.updated_at.isoformat(), order.id),
            )
            self._db.commit()

    def get_order(self, order_id: str) -> Optional[Order]:
        with self._lock:
            row = self._db.execute("SELECT payload FROM orders WHERE id=?", (order_id,)).fetchone()
        return Order.from_dict(json.loads(row["payload"])) if row else None

    def get_by_key(self, idem_key: str) -> Optional[Order]:
        with self._lock:
            row = self._db.execute("SELECT payload FROM orders WHERE idem_key=?", (idem_key,)).fetchone()
        return Order.from_dict(json.loads(row["payload"])) if row else None

    def list_orders(self, *, open_only: bool = False, limit: int = 200) -> list[Order]:
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM orders ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
            ).fetchall()
        orders = [Order.from_dict(json.loads(r["payload"])) for r in rows]
        if open_only:
            orders = [o for o in orders if o.state not in TERMINAL_STATES]
        return orders

    # ---- audit --------------------------------------------------------
    def audit(self, kind: str, order_id: Optional[str], payload: dict[str, Any]) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO audit (ts, kind, order_id, payload) VALUES (?,?,?,?)",
                (utcnow().isoformat(), kind, order_id, json.dumps(payload, default=str)),
            )
            self._db.commit()

    def audit_events(self, order_id: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            if order_id:
                rows = self._db.execute(
                    "SELECT ts, kind, order_id, payload FROM audit WHERE order_id=? ORDER BY id", (order_id,)
                ).fetchall()
            else:
                rows = self._db.execute("SELECT ts, kind, order_id, payload FROM audit ORDER BY id").fetchall()
        return [
            {"ts": r["ts"], "kind": r["kind"], "order_id": r["order_id"], "payload": json.loads(r["payload"])}
            for r in rows
        ]

    # ---- recorded market snapshots -----------------------------------
    def record_snapshot(
        self,
        symbol: str,
        recorded_at: datetime,
        as_of: datetime,
        source: str,
        fictional: bool,
        timestamp_verified: bool,
        payload: dict[str, Any],
    ) -> None:
        """Append one observed snapshot. Rows are never updated; `fictional` keeps made-up data separable."""
        with self._lock:
            self._db.execute(
                "INSERT INTO snapshots (symbol, recorded_at, as_of, source, fictional, timestamp_verified, payload)"
                " VALUES (?,?,?,?,?,?,?)",
                (
                    symbol,
                    recorded_at.isoformat(),
                    as_of.isoformat(),
                    source,
                    int(fictional),
                    int(timestamp_verified),
                    json.dumps(payload, default=str),
                ),
            )
            self._db.commit()

    def list_snapshots(
        self,
        symbol: Optional[str] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        include_fictional: bool = False,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Oldest first, so a replay can walk them in order. Fictional rows only when asked for."""
        where, args = [], []  # type: list[str], list[Any]
        if symbol:
            where.append("symbol=?")
            args.append(symbol)
        if since:
            where.append("recorded_at>=?")
            args.append(since.isoformat())
        if until:
            where.append("recorded_at<?")
            args.append(until.isoformat())
        if not include_fictional:
            where.append("fictional=0")
        sql = "SELECT * FROM snapshots" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY recorded_at, id LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, (*args, max(1, min(limit, 100_000)))).fetchall()
        return [
            {
                "id": r["id"],
                "symbol": r["symbol"],
                "recorded_at": r["recorded_at"],
                "as_of": r["as_of"],
                "source": r["source"],
                "fictional": bool(r["fictional"]),
                "timestamp_verified": bool(r["timestamp_verified"]),
                "payload": json.loads(r["payload"]),
            }
            for r in rows
        ]

    def prune_snapshots(self, before: datetime) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM snapshots WHERE recorded_at<?", (before.isoformat(),))
            self._db.commit()
            return cur.rowcount

    def snapshot_stats(self) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(fictional), 0) AS fake, MIN(recorded_at) AS oldest,"
                " MAX(recorded_at) AS newest FROM snapshots"
            ).fetchone()
        n, fake = int(row["n"]), int(row["fake"])
        return {"total": n, "real": n - fake, "fictional": fake, "oldest": row["oldest"], "newest": row["newest"]}

    # ---- data-quality log --------------------------------------------
    def record_data_issue(self, ts: datetime, symbol: str, kind: str, severity: str, count: int, detail: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO data_issues (ts, symbol, kind, severity, count, detail) VALUES (?,?,?,?,?,?)",
                (ts.isoformat(), symbol, kind, severity, int(count), detail[:200]),
            )
            self._db.commit()

    def data_issue_summary(self, since: datetime) -> dict[str, dict[str, Any]]:
        """Per issue kind since `since`: severity, how many times it occurred, and how many rows/cycles it touched."""
        with self._lock:
            rows = self._db.execute(
                "SELECT kind, severity, COUNT(*) AS events, SUM(count) AS items FROM data_issues"
                " WHERE ts>=? GROUP BY kind, severity ORDER BY kind",
                (since.isoformat(),),
            ).fetchall()
        return {r["kind"]: {"severity": r["severity"], "events": int(r["events"]), "items": int(r["items"])} for r in rows}

    def prune_data_issues(self, before: datetime) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM data_issues WHERE ts<?", (before.isoformat(),))
            self._db.commit()
            return cur.rowcount

    # ---- key/value state ---------------------------------------------
    def get_state(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._db.execute("SELECT v FROM state WHERE k=?", (key,)).fetchone()
        return row["v"] if row else default

    def set_state(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO state (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                (key, value),
            )
            self._db.commit()


__all__ = ["Store", "OrderState"]
