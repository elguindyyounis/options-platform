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
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    kind TEXT NOT NULL,
    disposition TEXT NOT NULL,
    contract TEXT NOT NULL,
    strategy TEXT NOT NULL,
    ref_price REAL,
    order_id TEXT,
    fictional INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions(ts);
CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    equity REAL NOT NULL,
    cash REAL NOT NULL,
    open_premium REAL NOT NULL,
    fictional INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_equity_ts ON equity(ts);
CREATE TABLE IF NOT EXISTS agent_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent TEXT NOT NULL,
    weight REAL NOT NULL,
    n INTEGER NOT NULL,
    accuracy REAL,
    fictional INTEGER NOT NULL,
    note TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hypotheses (
    id TEXT PRIMARY KEY,
    registered_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hypothesis_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hypothesis_id TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);
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

    # ---- equity curve ------------------------------------------------
    def record_equity(self, ts: datetime, equity: float, cash: float, open_premium: float, fictional: bool) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO equity (ts, equity, cash, open_premium, fictional) VALUES (?,?,?,?,?)",
                (ts.isoformat(), equity, cash, open_premium, int(fictional)),
            )
            self._db.commit()

    def list_equity(self, limit: int = 500, fictional: Optional[bool] = None) -> list[dict[str, Any]]:
        """The newest `limit` points, returned oldest first. `fictional` keeps made-up and real curves apart."""
        sql = "SELECT * FROM equity" + ("" if fictional is None else " WHERE fictional=?")
        args: tuple[Any, ...] = () if fictional is None else (int(fictional),)
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY ts DESC, id DESC LIMIT ?", (*args, max(1, min(limit, 5000)))).fetchall()
        return [{"ts": r["ts"], "equity": r["equity"], "cash": r["cash"], "open_premium": r["open_premium"],
                 "fictional": bool(r["fictional"])} for r in reversed(rows)]

    def prune_equity(self, before: datetime) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM equity WHERE ts<?", (before.isoformat(),))
            self._db.commit()
            return cur.rowcount

    # ---- learned agent weights: append-only audit trail, the latest row per agent is the live value ----
    def record_agent_weight(self, ts: datetime, agent: str, weight: float, n: int, accuracy: Optional[float],
                            fictional: bool, note: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO agent_weights (ts, agent, weight, n, accuracy, fictional, note) VALUES (?,?,?,?,?,?,?)",
                (ts.isoformat(), agent, weight, n, accuracy, int(fictional), note[:300]))
            self._db.commit()

    def latest_agent_weights(self, fictional: bool) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM agent_weights WHERE fictional=? ORDER BY id", (int(fictional),)).fetchall()
        return {r["agent"]: {"weight": r["weight"], "n": r["n"], "accuracy": r["accuracy"], "ts": r["ts"]} for r in rows}

    def list_agent_weights(self, fictional: bool, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM agent_weights WHERE fictional=? ORDER BY id DESC LIMIT ?",
                                    (int(fictional), max(1, min(limit, 500)))).fetchall()
        return [{"ts": r["ts"], "agent": r["agent"], "weight": r["weight"], "n": r["n"], "accuracy": r["accuracy"],
                 "note": r["note"]} for r in rows]

    # ---- pre-registered hypotheses (append-only: no update, no delete) -
    def register_hypothesis(self, registered_at: datetime, content_hash: str, payload: dict[str, Any]) -> str:
        with self._lock:
            n = self._db.execute("SELECT COUNT(*) FROM hypotheses").fetchone()[0]
            hid = f"H-{n + 1:04d}"
            self._db.execute(
                "INSERT INTO hypotheses (id, registered_at, content_hash, payload) VALUES (?,?,?,?)",
                (hid, registered_at.isoformat(), content_hash, json.dumps({**payload, "id": hid}, sort_keys=True)),
            )
            self._db.commit()
            return hid

    def get_hypothesis(self, hid: str) -> Optional[dict[str, Any]]:
        with self._lock:
            r = self._db.execute("SELECT * FROM hypotheses WHERE id=?", (hid,)).fetchone()
        if r is None:
            return None
        return {"id": r["id"], "registered_at": r["registered_at"], "content_hash": r["content_hash"],
                "payload": json.loads(r["payload"])}

    def list_hypotheses(self) -> list[dict[str, Any]]:
        with self._lock:
            ids = [r["id"] for r in self._db.execute("SELECT id FROM hypotheses ORDER BY id").fetchall()]
        return [h for h in (self.get_hypothesis(i) for i in ids) if h]

    def record_hypothesis_result(
        self, hid: str, evaluated_at: datetime, mode: str, status: str, payload: dict[str, Any]
    ) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO hypothesis_results (hypothesis_id, evaluated_at, mode, status, payload) VALUES (?,?,?,?,?)",
                (hid, evaluated_at.isoformat(), mode, status, json.dumps(payload, default=str)),
            )
            self._db.commit()

    def hypothesis_results(self, hid: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM hypothesis_results WHERE hypothesis_id=? ORDER BY id", (hid,)
            ).fetchall()
        return [{"evaluated_at": r["evaluated_at"], "mode": r["mode"], "status": r["status"],
                 "payload": json.loads(r["payload"])} for r in rows]

    # ---- decision journal --------------------------------------------
    def record_decision(
        self,
        ts: datetime,
        symbol: str,
        kind: str,
        disposition: str,
        contract: str,
        strategy: str,
        ref_price: Optional[float],
        order_id: Optional[str],
        fictional: bool,
        payload: dict[str, Any],
    ) -> int:
        """Append-only. A decision is never edited; outcomes are computed from it later, not written into it."""
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO decisions (ts, symbol, kind, disposition, contract, strategy, ref_price, order_id,"
                " fictional, payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (ts.isoformat(), symbol, kind, disposition, contract, strategy, ref_price, order_id, int(fictional),
                 json.dumps(payload, default=str)),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def list_decisions(
        self,
        kind: Optional[str] = None,
        include_fictional: bool = True,
        newest_first: bool = True,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        where, args = [], []  # type: list[str], list[Any]
        if kind:
            where.append("kind=?")
            args.append(kind)
        if not include_fictional:
            where.append("fictional=0")
        sql = "SELECT * FROM decisions" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY ts DESC, id DESC LIMIT ?" if newest_first else " ORDER BY ts, id LIMIT ?"
        with self._lock:
            rows = self._db.execute(sql, (*args, max(1, min(limit, 100_000)))).fetchall()
        return [
            {
                "id": r["id"], "ts": r["ts"], "symbol": r["symbol"], "kind": r["kind"],
                "disposition": r["disposition"], "contract": r["contract"], "strategy": r["strategy"],
                "ref_price": r["ref_price"], "order_id": r["order_id"], "fictional": bool(r["fictional"]),
                "payload": json.loads(r["payload"]),
            }
            for r in rows
        ]

    def first_snapshot_at_or_after(
        self, symbol: str, when: datetime, include_fictional: bool = False
    ) -> Optional[dict[str, Any]]:
        sql = "SELECT * FROM snapshots WHERE symbol=? AND recorded_at>=?" + ("" if include_fictional else " AND fictional=0")
        with self._lock:
            r = self._db.execute(sql + " ORDER BY recorded_at, id LIMIT 1", (symbol, when.isoformat())).fetchone()
        if r is None:
            return None
        return {"id": r["id"], "symbol": r["symbol"], "recorded_at": r["recorded_at"], "fictional": bool(r["fictional"]),
                "payload": json.loads(r["payload"])}

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
