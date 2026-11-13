"""Order lifecycle: risk gate -> broker -> reconciliation, as an explicit state machine.

Services move orders between states; nothing else does. A broker call that raises an unexpected
error leaves the order in ERROR_RECONCILE_REQUIRED, never guessed to have failed or succeeded.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from .broker.base import BrokerAdapter, BrokerRejected
from .models import (
    STATUS_CANCELLED,
    STATUS_FILLED,
    STATUS_PARTIALLY_FILLED,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
    TERMINAL_STATES,
    BrokerOrderStatus,
    Mode,
    OptionContract,
    Order,
    OrderIntent,
    OrderState,
    Side,
    utcnow,
)
from .risk import RiskPolicy, evaluate
from .store import Store

S = OrderState

TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    S.DRAFT: frozenset({S.RISK_REJECTED, S.RISK_APPROVED}),
    S.RISK_APPROVED: frozenset({S.SUBMITTED, S.BROKER_REJECTED, S.ERROR_RECONCILE_REQUIRED}),
    S.SUBMITTED: frozenset(
        {S.PARTIALLY_FILLED, S.FILLED, S.CANCELLED, S.BROKER_REJECTED, S.ERROR_RECONCILE_REQUIRED}
    ),
    S.PARTIALLY_FILLED: frozenset(
        {S.PARTIALLY_FILLED, S.FILLED, S.CANCELLED, S.ERROR_RECONCILE_REQUIRED}
    ),
    S.ERROR_RECONCILE_REQUIRED: frozenset(
        {S.SUBMITTED, S.PARTIALLY_FILLED, S.FILLED, S.CANCELLED, S.BROKER_REJECTED}
    ),
    S.RISK_REJECTED: frozenset(),
    S.FILLED: frozenset(),
    S.CANCELLED: frozenset(),
    S.BROKER_REJECTED: frozenset(),
}

_BROKER_STATUS_TO_STATE = {
    STATUS_SUBMITTED: S.SUBMITTED,
    STATUS_PARTIALLY_FILLED: S.PARTIALLY_FILLED,
    STATUS_FILLED: S.FILLED,
    STATUS_CANCELLED: S.CANCELLED,
    STATUS_REJECTED: S.BROKER_REJECTED,
}


class LiveTradingDisabled(RuntimeError):
    """Raised if an adapter that is not in PAPER mode is handed to the order manager."""


class InvalidTransition(RuntimeError):
    pass


REPORT_ORDER_LIMIT = 1000
MIN_TRADES_FOR_DESCRIPTION = 30


def _wilson_95(wins: int, n: int) -> list[float]:
    """95% Wilson interval for a win rate, in percent. Wide when n is small, which is the point."""
    z = 1.96
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return [round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)]


def evidence_summary(closed: list[dict[str, Any]], truncated: bool = False) -> dict[str, Any]:
    """How much weight the closed-trade numbers can bear. Display-only; changes nothing that trades.

    Fail-closed wording: below MIN_TRADES_FOR_DESCRIPTION closed trades the status is
    INSUFFICIENT_SAMPLE. Even above it the status is only DESCRIPTIVE_ONLY: paper fills on one
    data feed never establish an edge.
    """
    n = len(closed)
    wins = sum(1 for c in closed if c["pnl"] > 0)
    pnls = [c["pnl"] for c in closed]
    total = round(sum(pnls), 2)
    best = max(pnls) if pnls else None
    underlyings = {str(c["contract"]).strip()[:-15].strip() or str(c["contract"]).strip() for c in closed}
    status = "INSUFFICIENT_SAMPLE" if n < MIN_TRADES_FOR_DESCRIPTION else "DESCRIPTIVE_ONLY"
    notes = []
    if n < MIN_TRADES_FOR_DESCRIPTION:
        notes.append(f"Only {n} closed trades; fewer than {MIN_TRADES_FOR_DESCRIPTION}. Win rate and P&L are anecdotes.")
    if truncated:
        notes.append(f"More than {REPORT_ORDER_LIMIT} orders exist; older closed trades are NOT included in these totals.")
    if n and best is not None and best > 0 and total > 0 and total - best <= 0:
        notes.append("Total realized P&L is positive only because of the single best trade.")
    if n and len(underlyings) == 1:
        notes.append("All closed trades are in one underlying.")
    return {
        "status": status,
        "min_trades_for_description": MIN_TRADES_FOR_DESCRIPTION,
        "closed_trades": n,
        "distinct_underlyings": len(underlyings),
        "win_rate_95ci_pct": _wilson_95(wins, n) if n else None,
        "realized_pnl_without_best_trade": round(total - best, 2) if n > 1 and best is not None else None,
        "report_truncated": truncated,
        "notes": notes,
    }


class OrderManager:
    def __init__(
        self,
        broker: BrokerAdapter,
        store: Store,
        policy: Optional[RiskPolicy] = None,
        clock: Callable[[], datetime] = utcnow,
    ) -> None:
        self.broker = broker
        self.store = store
        self.policy = policy or RiskPolicy()
        self.clock = clock
        self._lock = threading.RLock()

    # ---- kill switch --------------------------------------------------
    def kill_switch_active(self) -> bool:
        return self.store.get_state("kill_switch", "0") == "1"

    def set_kill_switch(self, active: bool, reason: str = "") -> None:
        self.store.set_state("kill_switch", "1" if active else "0")
        self.store.audit("kill_switch", None, {"active": active, "reason": reason[:200]})

    # ---- submit -------------------------------------------------------
    def submit(self, intent: OrderIntent) -> Order:
        """Risk-check and place one BUY_TO_OPEN or SELL_TO_CLOSE limit order."""
        with self._lock:
            existing = self.store.get_by_key(intent.idempotency_key)
            if existing is not None:
                if existing.intent != intent:
                    raise ValueError("Idempotency key was already used with different order details")
                return existing
            if self.broker.mode is not Mode.PAPER:
                raise LiveTradingDisabled("Only PAPER broker adapters are accepted")

            order = Order.new(intent, self.clock())
            self.store.insert_order(order)
            self.store.audit("order_created", order.id, {"intent": intent.to_dict()})

            # Fresh broker data immediately before the decision, never cached or earlier data.
            quote = None
            quote_error = ""
            try:
                quote = self.broker.get_quote(intent.contract)
            except Exception as exc:  # noqa: BLE001 - any failure means "no usable quote"
                quote_error = f"Quote lookup failed: {type(exc).__name__}"
            try:
                account = self.broker.get_account()
                positions = self.broker.get_positions()
            except Exception as exc:  # noqa: BLE001
                return self._reject(order, [f"Broker account data unavailable: {type(exc).__name__}"])

            pending_close = 0
            if intent.side is Side.SELL_TO_CLOSE:
                pending_close = self._pending_close_qty(intent.contract)
                held = [p for p in positions if p.contract == intent.contract]
                if held:
                    order.cost_basis = held[0].avg_cost

            decision = evaluate(
                intent,
                quote,
                account,
                positions,
                self.policy,
                now=self.clock(),
                kill_switch=self.kill_switch_active(),
                pending_close_qty=pending_close,
            )
            order.risk_warnings = decision.warnings
            if not decision.allowed:
                failures = list(decision.failures)
                if quote_error:
                    failures.append(quote_error)
                return self._reject(order, failures)

            self._transition(order, S.RISK_APPROVED, "Passed risk policy " + decision.policy_version)
            try:
                status = self.broker.submit_limit_order(intent)
            except BrokerRejected as exc:
                self._transition(order, S.BROKER_REJECTED, f"Broker rejected: {str(exc)[:120]}")
                return order
            except Exception as exc:  # noqa: BLE001 - outcome unknown: do NOT assume failure
                self._transition(
                    order,
                    S.ERROR_RECONCILE_REQUIRED,
                    f"Broker submit raised {type(exc).__name__}; outcome unknown, reconcile",
                )
                return order
            self._apply_status(order, status)
            return order

    # ---- cancel -------------------------------------------------------
    def cancel(self, order_id: str) -> Order:
        with self._lock:
            order = self._require(order_id)
            if order.state not in (S.SUBMITTED, S.PARTIALLY_FILLED) or not order.broker_order_id:
                raise InvalidTransition(f"Order in state {order.state.value} cannot be cancelled")
            status = self.broker.cancel_order(order.broker_order_id)
            self._apply_status(order, status)
            return order

    # ---- reconcile ----------------------------------------------------
    def reconcile(self, *, no_record_after: timedelta = timedelta(seconds=60)) -> list[str]:
        """Re-read every non-terminal order from the broker. Returns the ids that changed."""
        changed: list[str] = []
        with self._lock:
            for order in self.store.list_orders(open_only=True):
                if order.state in (S.DRAFT,):
                    continue
                before = (order.state, order.filled_qty, order.avg_fill_price)
                try:
                    if order.broker_order_id:
                        status: Optional[BrokerOrderStatus] = self.broker.get_order_status(order.broker_order_id)
                    else:
                        status = self.broker.find_order_by_client_id(order.intent.idempotency_key)
                except Exception as exc:  # noqa: BLE001
                    self.store.audit("reconcile_error", order.id, {"error": type(exc).__name__})
                    continue
                if status is None:
                    # The broker confirms it has no such order, but only trust that after a grace
                    # period so a slow, eventually consistent broker is not mistaken for "never sent".
                    if self.clock() - order.updated_at >= no_record_after:
                        self._transition(order, S.BROKER_REJECTED, "Broker has no record of this order")
                else:
                    self._apply_status(order, status)
                if (order.state, order.filled_qty, order.avg_fill_price) != before:
                    changed.append(order.id)
        return changed

    def submit_buy(self, intent: OrderIntent) -> Order:
        if intent.side is not Side.BUY_TO_OPEN:
            raise ValueError("submit_buy requires a BUY_TO_OPEN intent")
        return self.submit(intent)

    def _pending_close_qty(self, contract: OptionContract) -> int:
        """Quantity already being sold by working orders, so exits can never double-sell a position."""
        active = (S.RISK_APPROVED, S.SUBMITTED, S.PARTIALLY_FILLED, S.ERROR_RECONCILE_REQUIRED)
        total = 0
        for o in self.store.list_orders(open_only=True, limit=1000):
            if o.intent.side is Side.SELL_TO_CLOSE and o.intent.contract == contract and o.state in active:
                total += max(0, o.intent.quantity - o.filled_qty)
        return total

    def entry_time(self, contract: OptionContract) -> Optional[datetime]:
        """When the most recent filled buy of this contract completed (None if unknown)."""
        for o in self.store.list_orders(limit=1000):  # newest first
            if o.intent.side is Side.BUY_TO_OPEN and o.intent.contract == contract and o.state is S.FILLED:
                return o.updated_at
        return None

    def last_close_time(self, contract: OptionContract) -> Optional[datetime]:
        """When this contract was most recently sold (None if never)."""
        for o in self.store.list_orders(limit=1000):  # newest first
            if o.intent.side is Side.SELL_TO_CLOSE and o.intent.contract == contract and o.state is S.FILLED:
                return o.updated_at
        return None

    def report(self) -> dict[str, Any]:
        """Realized P&L from closed paper trades plus bid-marked open positions."""
        closed = []
        fetched = self.store.list_orders(limit=REPORT_ORDER_LIMIT + 1)
        truncated = len(fetched) > REPORT_ORDER_LIMIT
        for o in fetched[:REPORT_ORDER_LIMIT]:
            if (
                o.intent.side is Side.SELL_TO_CLOSE
                and o.state is S.FILLED
                and o.cost_basis is not None
                and o.avg_fill_price
            ):
                pnl = round((o.avg_fill_price - o.cost_basis) * o.filled_qty * o.intent.contract.multiplier, 2)
                closed.append(
                    {
                        "order_id": o.id,
                        "contract": o.intent.contract.occ_symbol.strip(),
                        "quantity": o.filled_qty,
                        "entry": o.cost_basis,
                        "exit": o.avg_fill_price,
                        "pnl": pnl,
                        "closed_at": o.updated_at.isoformat(),
                    }
                )
        wins = sum(1 for c in closed if c["pnl"] > 0)
        open_rows = []
        for p in self.broker.get_positions():
            row: dict[str, Any] = {
                "contract": p.contract.occ_symbol.strip(),
                "quantity": p.quantity,
                "avg_cost": p.avg_cost,
                "mark": None,
                "unrealized_pnl": None,
                "mark_quality": "UNOBSERVABLE",
            }
            try:
                q = self.broker.get_quote(p.contract)
                if q.is_valid() and q.bid > 0:
                    row.update(
                        mark=q.bid,
                        unrealized_pnl=round((q.bid - p.avg_cost) * p.quantity * p.contract.multiplier, 2),
                        mark_quality="BID",
                    )
            except Exception:  # noqa: BLE001 - an unobservable mark is reported, never guessed
                pass
            open_rows.append(row)
        return {
            "closed_trades": len(closed),
            "wins": wins,
            "realized_pnl": round(sum(c["pnl"] for c in closed), 2),
            "win_rate_pct": round(wins / len(closed) * 100, 1) if closed else None,
            "closed": closed[:50],
            "open": open_rows,
            "evidence": evidence_summary(closed, truncated),
            "caveat": "Paper results with simulated fills. A small sample says nothing about a real edge.",
        }

    # ---- queries ------------------------------------------------------
    def get(self, order_id: str) -> Optional[Order]:
        return self.store.get_order(order_id)

    def list(self, *, open_only: bool = False) -> list[Order]:
        return self.store.list_orders(open_only=open_only)

    def portfolio(self) -> dict[str, Any]:
        return {
            "account": self.broker.get_account().to_dict(),
            "positions": [p.to_dict() for p in self.broker.get_positions()],
            "kill_switch": self.kill_switch_active(),
            "policy": self.policy.to_dict(),
        }

    # ---- internals ----------------------------------------------------
    def _require(self, order_id: str) -> Order:
        order = self.store.get_order(order_id)
        if order is None:
            raise KeyError(order_id)
        return order

    def _reject(self, order: Order, failures: list[str]) -> Order:
        order.risk_failures = failures
        self._transition(order, S.RISK_REJECTED, "; ".join(failures)[:300])
        return order

    def _transition(self, order: Order, new_state: OrderState, reason: str) -> None:
        if new_state not in TRANSITIONS[order.state]:
            raise InvalidTransition(f"{order.state.value} -> {new_state.value} is not allowed")
        now = self.clock()
        order.state = new_state
        order.updated_at = now
        order.history.append({"ts": now.isoformat(), "state": new_state.value, "reason": reason})
        self.store.save_order(order)
        self.store.audit("order_state", order.id, {"state": new_state.value, "reason": reason})

    def _apply_status(self, order: Order, status: BrokerOrderStatus) -> None:
        if order.state in TERMINAL_STATES:
            return
        target = _BROKER_STATUS_TO_STATE.get(status.status)
        qty = order.intent.quantity
        inconsistent = (
            target is None
            or not 0 <= status.filled_qty <= qty
            or (target is S.FILLED and status.filled_qty != qty)
            or (target in (S.FILLED, S.PARTIALLY_FILLED) and not (status.avg_fill_price or 0) > 0)
        )
        if inconsistent:
            if order.state is not S.ERROR_RECONCILE_REQUIRED:
                self._transition(order, S.ERROR_RECONCILE_REQUIRED, f"Inconsistent broker status {status.status!r}")
            return
        order.broker_order_id = status.broker_order_id or order.broker_order_id
        order.filled_qty = status.filled_qty
        order.avg_fill_price = status.avg_fill_price
        if order.state is S.RISK_APPROVED and target not in (S.SUBMITTED, S.BROKER_REJECTED):
            self._transition(order, S.SUBMITTED, "Accepted by broker")
        if target is not order.state or target is S.PARTIALLY_FILLED:
            self._transition(order, target, f"Broker status {status.status}")
        else:
            # Refresh fill fields only. updated_at marks the last real state change, so a routine
            # reconcile must not make a resting order look fresh (that would defeat stale-order cancels).
            self.store.save_order(order)
