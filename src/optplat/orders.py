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
    Order,
    OrderIntent,
    OrderState,
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
    def submit_buy(self, intent: OrderIntent) -> Order:
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

            decision = evaluate(
                intent,
                quote,
                account,
                positions,
                self.policy,
                now=self.clock(),
                kill_switch=self.kill_switch_active(),
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
            order.updated_at = self.clock()
            self.store.save_order(order)
