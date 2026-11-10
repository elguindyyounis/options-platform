"""The contract every broker integration must satisfy.

Implement this for your broker, then subclass ``tests/conformance.py::BrokerConformance``
to prove the adapter behaves the way the order manager assumes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..models import Account, BrokerOrderStatus, Mode, OptionContract, OrderIntent, Position, Quote


class BrokerRejected(Exception):
    """The broker definitively refused the order (it was NOT placed)."""


class QuoteUnavailable(Exception):
    """No usable quote could be obtained for the contract."""


class BrokerAdapter(ABC):
    #: PAPER adapters only. The order manager refuses any adapter whose mode is not PAPER.
    mode: Mode = Mode.PAPER
    name: str = "abstract"

    @abstractmethod
    def healthcheck(self) -> dict[str, Any]:
        """Return at least ``{"connected": bool}``. Must never place or change orders."""

    @abstractmethod
    def get_account(self) -> Account: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_quote(self, contract: OptionContract) -> Quote:
        """Fresh two-sided quote. Raise ``QuoteUnavailable`` rather than returning stale/empty data."""

    @abstractmethod
    def submit_limit_order(self, intent: OrderIntent) -> BrokerOrderStatus:
        """Buy-to-open limit order.

        MUST be idempotent on ``intent.idempotency_key``: submitting the same key twice returns the
        existing order instead of creating a second one (use the broker's client order id / orderRef).
        Raise ``BrokerRejected`` only when certain the order was not placed.
        """

    @abstractmethod
    def cancel_order(self, broker_order_id: str) -> BrokerOrderStatus: ...

    @abstractmethod
    def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus: ...

    @abstractmethod
    def find_order_by_client_id(self, client_id: str) -> Optional[BrokerOrderStatus]:
        """Look an order up by our idempotency key. ``None`` means the broker has no such order.

        Used after a crash or timeout to learn whether a submit actually went through.
        """

    @abstractmethod
    def get_open_orders(self) -> list[BrokerOrderStatus]: ...
