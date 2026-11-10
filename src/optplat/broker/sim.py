"""Deterministic in-memory paper broker with conservative fills.

Buys fill at ask plus slippage, and only when the limit covers that price. Anything else rests
unfilled. It never invents a fill from a missing quote.
"""
from __future__ import annotations

import threading
from typing import Any, Optional

from ..models import (
    STATUS_CANCELLED,
    STATUS_FILLED,
    STATUS_SUBMITTED,
    Account,
    BrokerOrderStatus,
    Mode,
    OptionContract,
    OrderIntent,
    Position,
    Quote,
)
from .base import BrokerAdapter, BrokerRejected, QuoteUnavailable


class SimBroker(BrokerAdapter):
    mode = Mode.PAPER
    name = "sim"

    def __init__(self, starting_cash: float = 100_000.0, slippage_pct: float = 0.5) -> None:
        self.cash = float(starting_cash)
        self.slippage_pct = float(slippage_pct)
        self._quotes: dict[OptionContract, Quote] = {}
        self._orders: dict[str, dict[str, Any]] = {}
        self._by_client: dict[str, str] = {}
        self._positions: dict[OptionContract, list[float]] = {}  # contract -> [qty, avg_cost]
        self._seq = 0
        self._lock = threading.RLock()

    # ---- test / demo hooks -------------------------------------------
    def set_quote(self, quote: Quote) -> None:
        with self._lock:
            self._quotes[quote.contract] = quote
            for rec in self._orders.values():
                if rec["status"] == STATUS_SUBMITTED and rec["intent"].contract == quote.contract:
                    self._try_fill(rec, quote)

    # ---- BrokerAdapter -----------------------------------------------
    def healthcheck(self) -> dict[str, Any]:
        return {"connected": True, "broker": self.name, "mode": self.mode.value}

    def get_quote(self, contract: OptionContract) -> Quote:
        with self._lock:
            quote = self._quotes.get(contract)
        if quote is None:
            raise QuoteUnavailable(f"No simulated quote for {contract.occ_symbol}")
        return quote

    def get_account(self) -> Account:
        with self._lock:
            open_premium = 0.0
            marks = 0.0
            for contract, (qty, avg_cost) in self._positions.items():
                open_premium += avg_cost * contract.multiplier * qty
                quote = self._quotes.get(contract)
                mark = quote.bid if quote and quote.is_valid() else avg_cost
                marks += mark * contract.multiplier * qty
            return Account(
                equity=round(self.cash + marks, 2),
                cash=round(self.cash, 2),
                open_premium=round(open_premium, 2),
            )

    def get_positions(self) -> list[Position]:
        with self._lock:
            return [
                Position(contract=c, quantity=int(q), avg_cost=round(cost, 4))
                for c, (q, cost) in self._positions.items()
                if q > 0
            ]

    def submit_limit_order(self, intent: OrderIntent) -> BrokerOrderStatus:
        with self._lock:
            existing = self._by_client.get(intent.idempotency_key)
            if existing:
                return self._status(self._orders[existing])
            quote = self._quotes.get(intent.contract)
            if quote is None:
                raise BrokerRejected(f"No quote for {intent.contract.occ_symbol}")
            self._seq += 1
            broker_id = f"SIM-{self._seq:06d}"
            rec = {
                "id": broker_id,
                "client_id": intent.idempotency_key,
                "intent": intent,
                "status": STATUS_SUBMITTED,
                "filled_qty": 0,
                "avg_fill_price": None,
            }
            self._orders[broker_id] = rec
            self._by_client[intent.idempotency_key] = broker_id
            self._try_fill(rec, quote)
            return self._status(rec)

    def cancel_order(self, broker_order_id: str) -> BrokerOrderStatus:
        with self._lock:
            rec = self._orders.get(broker_order_id)
            if rec is None:
                raise BrokerRejected(f"Unknown order {broker_order_id}")
            if rec["status"] == STATUS_SUBMITTED:
                rec["status"] = STATUS_CANCELLED
            return self._status(rec)

    def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        with self._lock:
            rec = self._orders.get(broker_order_id)
            if rec is None:
                raise BrokerRejected(f"Unknown order {broker_order_id}")
            return self._status(rec)

    def find_order_by_client_id(self, client_id: str) -> Optional[BrokerOrderStatus]:
        with self._lock:
            broker_id = self._by_client.get(client_id)
            return self._status(self._orders[broker_id]) if broker_id else None

    def get_open_orders(self) -> list[BrokerOrderStatus]:
        with self._lock:
            return [self._status(r) for r in self._orders.values() if r["status"] == STATUS_SUBMITTED]

    # ---- internals ----------------------------------------------------
    def _try_fill(self, rec: dict[str, Any], quote: Quote) -> None:
        intent: OrderIntent = rec["intent"]
        if not quote.is_valid():
            return
        fill_price = round(quote.ask * (1 + self.slippage_pct / 100), 2)
        cost = fill_price * intent.contract.multiplier * intent.quantity
        if intent.limit_price + 1e-9 < fill_price or cost > self.cash:
            return
        self.cash -= cost
        qty, avg = self._positions.get(intent.contract, [0, 0.0])
        new_qty = qty + intent.quantity
        self._positions[intent.contract] = [new_qty, (avg * qty + fill_price * intent.quantity) / new_qty]
        rec["status"] = STATUS_FILLED
        rec["filled_qty"] = intent.quantity
        rec["avg_fill_price"] = fill_price

    @staticmethod
    def _status(rec: dict[str, Any]) -> BrokerOrderStatus:
        return BrokerOrderStatus(
            broker_order_id=rec["id"],
            client_id=rec["client_id"],
            status=rec["status"],
            filled_qty=rec["filled_qty"],
            avg_fill_price=rec["avg_fill_price"],
        )
