"""SQLite persistence for orders, an append-only audit log and small key/value state."""
from __future__ import annotations

import json
import sqlite3
import threading
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
"""


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
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
