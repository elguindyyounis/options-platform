"""Interactive Brokers PAPER adapter: a skeleton for you to finish.

Every trading method raises NotImplementedError on purpose. Implement them with ``ib_async``
(``pip install -e .[ibkr]``), then run the shared conformance suite against it. See
docs/BROKER_INTEGRATION.md for the checklist. Live trading is not supported by this project.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from ..models import Account, BrokerOrderStatus, Mode, OptionContract, OrderIntent, Position, Quote
from .base import BrokerAdapter

ALLOWED_PAPER_PORTS = {7497, 7947, 4002}

_TODO = "Implement with ib_async; see docs/BROKER_INTEGRATION.md"


def ibkr_paper_config() -> tuple[str, int, str]:
    """Validate connection settings. Refuses anything that is not a local paper session."""
    host = os.environ.get("IBKR_HOST", "127.0.0.1")
    port = int(os.environ.get("IBKR_PAPER_PORT", "7497"))
    account = os.environ.get("IBKR_PAPER_ACCOUNT", "")
    if host not in ("localhost", "127.0.0.1"):
        raise ValueError("IBKR host must be local")
    if port not in ALLOWED_PAPER_PORTS:
        raise ValueError("IBKR paper-only port required (7497/7947/4002)")
    if not (account.startswith("DU") and account[2:].isdigit()):
        raise ValueError("A paper account id beginning with DU is required")
    return host, port, account


class IBKRPaperBroker(BrokerAdapter):
    mode = Mode.PAPER
    name = "ibkr_paper"

    def __init__(self) -> None:
        self.host, self.port, self.account_id = ibkr_paper_config()

    def healthcheck(self) -> dict[str, Any]:
        raise NotImplementedError(_TODO)

    def get_account(self) -> Account:
        raise NotImplementedError(_TODO)

    def get_positions(self) -> list[Position]:
        raise NotImplementedError(_TODO)

    def get_quote(self, contract: OptionContract) -> Quote:
        raise NotImplementedError(_TODO)

    def submit_limit_order(self, intent: OrderIntent) -> BrokerOrderStatus:
        raise NotImplementedError(_TODO)

    def cancel_order(self, broker_order_id: str) -> BrokerOrderStatus:
        raise NotImplementedError(_TODO)

    def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        raise NotImplementedError(_TODO)

    def find_order_by_client_id(self, client_id: str) -> Optional[BrokerOrderStatus]:
        raise NotImplementedError(_TODO)

    def get_open_orders(self) -> list[BrokerOrderStatus]:
        raise NotImplementedError(_TODO)
