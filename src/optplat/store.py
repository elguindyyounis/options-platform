"""SQLite persistence for orders, an append-only audit log and small key/value state."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from .models import Order, OrderState, Quote, TERMINAL_STATES, utcnow

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
CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at TEXT NOT NULL,
    symbol TEXT NOT NULL,
    underlying REAL NOT NULL,
    closes TEXT NOT NULL,
    as_of TEXT NOT NULL,
    source TEXT NOT NULL,
    timestamp_verified INTEGER NOT NULL,
    fictional INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_snapshots_symbol_rec ON market_snapshots(symbol, recorded_at);
CREATE TABLE IF NOT EXISTS market_quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER,
    recorded_at TEXT NOT NULL,
    underlying TEXT NOT NULL,
    expiry TEXT NOT NULL,
    right TEXT NOT NULL,
    strike REAL NOT NULL,
    bid REAL NOT NULL,
    ask REAL NOT NULL,
    volume INTEGER,
    open_interest INTEGER,
    iv REAL,
    as_of TEXT NOT NULL,
    source TEXT NOT NULL,
    timestamp_verified INTEGER NOT NULL,
    fictional INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_quotes_rec ON market_quotes(recorded_at);
CREATE INDEX IF NOT EXISTS idx_market_quotes_snap ON market_quotes(snapshot_id);
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

    # ---- market data recorder ----------------------------------------
    # Raw observations only: what a provider returned, when we recorded it, and where it came from.
    # `as_of` is the provider's claimed time and `timestamp_verified` says whether the venue supplied it.
    def record_snapshot(self, snap: Any, *, recorded_at: Optional[datetime] = None) -> int:
        """Persist a MarketSnapshot and its chain rows in one transaction. Returns the snapshot id."""
        rec = (recorded_at or utcnow()).isoformat()
        with self._lock:
            try:
                cur = self._db.execute(
                    "INSERT INTO market_snapshots (recorded_at, symbol, underlying, closes, as_of, source,"
                    " timestamp_verified, fictional) VALUES (?,?,?,?,?,?,?,?)",
                    (rec, snap.symbol, snap.underlying, json.dumps(list(snap.closes)), snap.as_of.isoformat(),
                     snap.source, int(snap.timestamp_verified), int(snap.fictional)),
                )
                snapshot_id = int(cur.lastrowid)
                self._db.executemany(
                    "INSERT INTO market_quotes (snapshot_id, recorded_at, underlying, expiry, right, strike, bid, ask,"
                    " volume, open_interest, iv, as_of, source, timestamp_verified, fictional)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [
                        (snapshot_id, rec, r.contract.underlying, r.contract.expiry.isoformat(), r.contract.right.value,
                         r.contract.strike, r.bid, r.ask, r.volume, r.open_interest, r.iv, snap.as_of.isoformat(),
                         snap.source, int(snap.timestamp_verified), int(snap.fictional))
                        for r in snap.rows
                    ],
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return snapshot_id

    def record_quotes(
        self, quotes: Iterable[Quote], *, fictional: bool, recorded_at: Optional[datetime] = None
    ) -> int:
        """Persist standalone quotes (e.g. for held positions). Returns the number stored."""
        rec = (recorded_at or utcnow()).isoformat()
        rows = [
            (rec, q.contract.underlying, q.contract.expiry.isoformat(), q.contract.right.value, q.contract.strike,
             q.bid, q.ask, q.as_of.isoformat(), q.source, int(q.timestamp_verified), int(fictional))
            for q in quotes
        ]
        if not rows:
            return 0
        with self._lock:
            try:
                self._db.executemany(
                    "INSERT INTO market_quotes (snapshot_id, recorded_at, underlying, expiry, right, strike, bid, ask,"
                    " as_of, source, timestamp_verified, fictional) VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        return len(rows)

    def recorder_counts(self) -> dict[str, int]:
        with self._lock:
            snaps = self._db.execute("SELECT COUNT(*) AS n FROM market_snapshots").fetchone()["n"]
            quotes = self._db.execute("SELECT COUNT(*) AS n FROM market_quotes").fetchone()["n"]
        return {"snapshots": snaps, "quotes": quotes}

    def recorded_snapshots(self, symbol: Optional[str] = None, limit: int = 100) -> list[dict[str, Any]]:
        """Snapshots in recording order (oldest first), each with its chain rows."""
        with self._lock:
            if symbol:
                heads = self._db.execute(
                    "SELECT * FROM market_snapshots WHERE symbol=? ORDER BY id LIMIT ?", (symbol, limit)
                ).fetchall()
            else:
                heads = self._db.execute("SELECT * FROM market_snapshots ORDER BY id LIMIT ?", (limit,)).fetchall()
            out = []
            for h in heads:
                rows = self._db.execute(
                    "SELECT underlying, expiry, right, strike, bid, ask, volume, open_interest, iv"
                    " FROM market_quotes WHERE snapshot_id=? ORDER BY id", (h["id"],)
                ).fetchall()
                out.append({
                    "id": h["id"], "recorded_at": h["recorded_at"], "symbol": h["symbol"],
                    "underlying": h["underlying"], "closes": json.loads(h["closes"]), "as_of": h["as_of"],
                    "source": h["source"], "timestamp_verified": bool(h["timestamp_verified"]),
                    "fictional": bool(h["fictional"]), "rows": [dict(r) for r in rows],
                })
        return out

    def purge_market_data(self, retention_days: int, *, now: Optional[datetime] = None) -> int:
        """Delete recordings older than ``retention_days`` (0 keeps everything). Returns rows removed."""
        if retention_days <= 0:
            return 0
        cutoff = ((now or utcnow()) - timedelta(days=retention_days)).isoformat()
        with self._lock:
            q = self._db.execute("DELETE FROM market_quotes WHERE recorded_at < ?", (cutoff,)).rowcount
            s = self._db.execute("DELETE FROM market_snapshots WHERE recorded_at < ?", (cutoff,)).rowcount
            self._db.commit()
        return q + s


__all__ = ["Store", "OrderState"]
