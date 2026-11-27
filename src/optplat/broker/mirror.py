"""Mirror the main simulated account's orders to the IBKR paper account (owner decision 2026-11-26).

The simulated broker stays the account of record: its fills, cash, positions and restore are unchanged, and nothing
IBKR does or fails to do can alter them. Every order the simulator accepts (after the risk policy and kill switch in
``OrderManager``) is also sent, in order, by one background worker, to ``IBKRPaperBroker`` with the same idempotency
key; cancels follow. Each outcome is written to the audit log (``ibkr_mirror_*``) so the two books can be compared.
While the queue is idle the worker reads back (never changes) IBKR orders still working, so a later fill is audited
too (``ibkr_mirror_status``). ``python -m optplat.mirror_report`` compares the two books.

Off unless ``OPTPLAT_IBKR_MIRROR=1``. A paper fill at IBKR is IBKR's simulator, not a real market.
"""
from __future__ import annotations

import queue
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ..models import (STATUS_CANCELLED, STATUS_FILLED, STATUS_PARTIALLY_FILLED, STATUS_REJECTED, STATUS_SUBMITTED,
                      BrokerOrderStatus, OrderIntent)
from .base import BrokerAdapter, BrokerRejected
from .ibkr import ID_PREFIX
from .sim import SimBroker

MAX_BACKLOG = 200
RETRY_DELAYS_S = (10.0, 30.0)   # an unknown outcome is retried by the same key; IBKR finds an order already placed   # beyond this, new mirror work is dropped and audited, never blocking the simulator
POLL_S = 60.0       # idle worker reads back still-working IBKR orders this often
MAX_TRACKED = 200   # still-working IBKR orders followed at once; the oldest is dropped beyond this
MAX_MISSES = 30     # read-backs in a row that fail before an order stops being followed (about 30 idle minutes)
TERMINAL = (STATUS_FILLED, STATUS_CANCELLED, STATUS_REJECTED)

Audit = Callable[[str, Optional[str], dict[str, Any]], None]


class MirroredSimBroker(SimBroker):
    name = "sim+ibkr_paper"

    def __init__(self, mirror: BrokerAdapter, *, background: bool = True, **sim_kwargs: Any) -> None:
        super().__init__(**sim_kwargs)
        self.mirror = mirror
        self._audit: Audit = lambda *_a: None
        self._keys: dict[str, str] = {}
        self._working: dict[str, tuple[str, int]] = {}   # key -> last IBKR (status, filled); touched by the worker only
        self._misses: dict[str, int] = {}
        self._background = background
        self.retry_delays_s: tuple[float, ...] = RETRY_DELAYS_S if background else ()
        self._work: "queue.Queue[tuple[Callable[..., None], tuple[Any, ...]]]" = queue.Queue(MAX_BACKLOG)
        self.last_mirror: dict[str, Any] = {"state": "idle", "at": None}
        if background:
            threading.Thread(target=self._drain, name="ibkr-mirror", daemon=True).start()

    def attach_audit(self, audit: Audit) -> None:
        self._audit = audit

    # ---- the simulator is the account of record ----------------------------------------------------------------------
    def submit_limit_order(self, intent: OrderIntent) -> BrokerOrderStatus:
        status = super().submit_limit_order(intent)
        self._keys[status.broker_order_id] = intent.idempotency_key
        if status.status in (STATUS_SUBMITTED, STATUS_PARTIALLY_FILLED, STATUS_FILLED):
            self._enqueue(self._mirror_submit, intent)
        return status

    def cancel_order(self, broker_order_id: str) -> BrokerOrderStatus:
        status = super().cancel_order(broker_order_id)
        key = self._keys.get(broker_order_id)
        if key:
            self._enqueue(self._mirror_cancel, key)
        return status

    def healthcheck(self) -> dict[str, Any]:
        """Never calls IBKR (a health check must stay fast); reports the mirror's last outcome instead."""
        return {**super().healthcheck(), "ibkr_mirror": {**self.last_mirror, "backlog": self._work.qsize()}}

    # ---- the mirror ----------------------------------------------------------------------------------------------------
    def _enqueue(self, fn: Callable[..., None], *args: Any) -> None:
        if not self._background:
            fn(*args)
            return
        try:
            self._work.put_nowait((fn, args))
        except queue.Full:
            self._record("ibkr_mirror_dropped", {"reason": "backlog full", "args": [str(a)[:80] for a in args]}, "dropped")

    def _drain(self) -> None:
        while True:
            try:
                fn, args = self._work.get(timeout=POLL_S)
            except queue.Empty:
                fn, args = self.poll_working, ()
            try:
                fn(*args)
            except Exception as exc:  # noqa: BLE001 - the worker must survive anything
                self._record("ibkr_mirror_error", {"error": type(exc).__name__}, "error")

    def _track(self, key: str, status: str, filled: int) -> None:
        if status in TERMINAL:
            self._working.pop(key, None)
            self._misses.pop(key, None)
            return
        self._working[key] = (status, filled)
        while len(self._working) > MAX_TRACKED:
            oldest = next(iter(self._working))
            self._working.pop(oldest)
            self._misses.pop(oldest, None)

    def poll_working(self) -> None:
        """Read back IBKR orders still working and audit any change. Read-only: never submits, cancels or retries."""
        for key, last in list(self._working.items()):
            try:
                s = self.mirror.get_order_status(ID_PREFIX + key)
            except Exception:  # noqa: BLE001 - unreachable or unknown now; try again next idle period, then give up
                self._misses[key] = self._misses.get(key, 0) + 1
                if self._misses[key] >= MAX_MISSES:
                    self._working.pop(key, None)
                    self._misses.pop(key, None)
                continue
            self._misses.pop(key, None)
            if (s.status, s.filled_qty) != last:
                self._record("ibkr_mirror_status", {"idempotency_key": key, "status": s.status,
                                                    "filled_qty": s.filled_qty, "avg_fill_price": s.avg_fill_price},
                             s.status)
            self._track(key, s.status, s.filled_qty)

    def _mirror_submit(self, intent: OrderIntent) -> None:
        base = {"idempotency_key": intent.idempotency_key, "side": intent.side.value, "quantity": intent.quantity,
                "limit_price": intent.limit_price, "contract": intent.contract.to_dict()}
        for attempt, delay in enumerate((0.0, *self.retry_delays_s)):
            if delay:
                time.sleep(delay)
            try:
                s = self.mirror.submit_limit_order(intent)   # idempotent: a retry finds an order already placed
            except BrokerRejected as exc:
                self._record("ibkr_mirror_rejected", {**base, "reason": str(exc)[:160]}, "rejected")
                return
            except Exception as exc:  # noqa: BLE001 - unknown outcome: retry by the same key, then give up loudly
                last = type(exc).__name__
                stage = getattr(self.mirror, "stage", None)
                self._record("ibkr_mirror_error", {**base, "error": last, "attempt": attempt + 1, "stage": stage}, "error")
                continue
            break
        else:
            return   # every attempt failed; each is in the audit log
        self._record("ibkr_mirror_submitted", {**base, "status": s.status, "filled_qty": s.filled_qty,
                                               "avg_fill_price": s.avg_fill_price}, s.status)
        self._track(intent.idempotency_key, s.status, s.filled_qty)

    def _mirror_cancel(self, key: str) -> None:
        try:
            s = self.mirror.cancel_order(ID_PREFIX + key)
        except Exception as exc:  # noqa: BLE001
            self._record("ibkr_mirror_cancel_error", {"idempotency_key": key, "error": type(exc).__name__}, "error")
        else:
            self._record("ibkr_mirror_cancelled", {"idempotency_key": key, "status": s.status, "filled_qty": s.filled_qty,
                                                   "avg_fill_price": s.avg_fill_price}, s.status)
            self._track(key, s.status, s.filled_qty)

    def catch_up(self, verified_quote: Callable[[Any], Any], now: datetime) -> list[dict[str, Any]]:
        """Sell at IBKR what this platform owns there but the simulator (the account of record) no longer holds, e.g.
        after a mirrored sell failed. Each sell needs a verified quote and is limited to bid - 1%. Buys nothing."""
        from ..models import OrderIntent, Side
        from ..pricing import sell_limit_for

        sim = {p.contract: p.quantity for p in self.get_positions()}
        results = []
        for pos in self.mirror.owned_positions():
            excess = pos.quantity - sim.get(pos.contract, 0)
            if excess <= 0:
                continue
            row: dict[str, Any] = {"contract": pos.contract.occ_symbol.strip(), "quantity": excess}
            quote = verified_quote(pos.contract)
            if quote is None or not quote.bid > 0:
                row["result"] = "NOT_VERIFIED"
                results.append(row)
                continue
            intent = OrderIntent(f"catchup-{pos.contract.occ_symbol.replace(' ', '')}-{int(now.timestamp())}"[:64],
                                 "mirror-catch-up", pos.contract, excess, sell_limit_for(quote.bid),
                                 note="sell IBKR paper holding the simulator no longer has", side=Side.SELL_TO_CLOSE)
            try:
                s = self.mirror.submit_limit_order(intent)
                row.update(result=s.status, filled_qty=s.filled_qty, limit_price=intent.limit_price)
            except Exception as exc:  # noqa: BLE001
                row.update(result="ERROR", error=type(exc).__name__, detail=str(exc)[:160])
            self._record("ibkr_mirror_catch_up", row, row["result"])
            results.append(row)
        return results

    def _record(self, kind: str, payload: dict[str, Any], state: str) -> None:
        self.last_mirror = {"state": state, "at": datetime.now(timezone.utc).isoformat(), "kind": kind}
        try:
            self._audit(kind, None, payload)
        except Exception:  # noqa: BLE001 - losing an audit line must not stop the mirror
            pass
