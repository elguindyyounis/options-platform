"""Domain types shared by the broker adapters, risk engine and order manager."""
from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Mode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class Right(str, Enum):
    CALL = "C"
    PUT = "P"


class OrderState(str, Enum):
    DRAFT = "DRAFT"
    RISK_REJECTED = "RISK_REJECTED"
    RISK_APPROVED = "RISK_APPROVED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    BROKER_REJECTED = "BROKER_REJECTED"
    ERROR_RECONCILE_REQUIRED = "ERROR_RECONCILE_REQUIRED"


TERMINAL_STATES = frozenset(
    {OrderState.RISK_REJECTED, OrderState.FILLED, OrderState.CANCELLED, OrderState.BROKER_REJECTED}
)

# Statuses a broker adapter may report (kept as plain strings so adapters stay decoupled).
STATUS_SUBMITTED = "SUBMITTED"
STATUS_PARTIALLY_FILLED = "PARTIALLY_FILLED"
STATUS_FILLED = "FILLED"
STATUS_CANCELLED = "CANCELLED"
STATUS_REJECTED = "REJECTED"


@dataclass(frozen=True)
class OptionContract:
    underlying: str
    expiry: date
    right: Right
    strike: float
    multiplier: int = 100

    @property
    def occ_symbol(self) -> str:
        return f"{self.underlying.upper():<6}{self.expiry:%y%m%d}{self.right.value}{round(self.strike * 1000):08d}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "underlying": self.underlying,
            "expiry": self.expiry.isoformat(),
            "right": self.right.value,
            "strike": self.strike,
            "multiplier": self.multiplier,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OptionContract":
        return cls(
            underlying=d["underlying"],
            expiry=date.fromisoformat(d["expiry"]),
            right=Right(d["right"]),
            strike=float(d["strike"]),
            multiplier=int(d.get("multiplier", 100)),
        )


@dataclass(frozen=True)
class Quote:
    contract: OptionContract
    bid: float
    ask: float
    as_of: datetime
    source: str
    # True only when the venue/broker supplied the quote time. Download time is NOT enough.
    timestamp_verified: bool = False

    def is_valid(self) -> bool:
        return (
            math.isfinite(self.bid)
            and math.isfinite(self.ask)
            and self.ask > 0
            and 0 <= self.bid <= self.ask
        )

    def spread_pct_of_ask(self) -> float:
        return (self.ask - self.bid) / self.ask * 100

    def age_seconds(self, now: datetime) -> float:
        return (now - self.as_of).total_seconds()


@dataclass(frozen=True)
class OrderIntent:
    """A request to BUY TO OPEN one long option via a limit order. Nothing else is supported."""

    idempotency_key: str
    candidate_id: str
    contract: OptionContract
    quantity: int
    limit_price: float
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "candidate_id": self.candidate_id,
            "contract": self.contract.to_dict(),
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "OrderIntent":
        return cls(
            idempotency_key=d["idempotency_key"],
            candidate_id=d["candidate_id"],
            contract=OptionContract.from_dict(d["contract"]),
            quantity=d["quantity"],
            limit_price=d["limit_price"],
            note=d.get("note", ""),
        )


@dataclass(frozen=True)
class Account:
    equity: float
    cash: float
    open_premium: float  # cost basis of open long options

    def to_dict(self) -> dict[str, Any]:
        return {"equity": self.equity, "cash": self.cash, "open_premium": self.open_premium}


@dataclass(frozen=True)
class Position:
    contract: OptionContract
    quantity: int
    avg_cost: float  # per share (premium), not per contract

    def to_dict(self) -> dict[str, Any]:
        return {"contract": self.contract.to_dict(), "quantity": self.quantity, "avg_cost": self.avg_cost}


@dataclass(frozen=True)
class BrokerOrderStatus:
    broker_order_id: str
    client_id: str
    status: str
    filled_qty: int = 0
    avg_fill_price: Optional[float] = None


@dataclass
class Order:
    id: str
    intent: OrderIntent
    state: OrderState
    created_at: datetime
    updated_at: datetime
    risk_failures: list[str] = field(default_factory=list)
    risk_warnings: list[str] = field(default_factory=list)
    broker_order_id: Optional[str] = None
    filled_qty: int = 0
    avg_fill_price: Optional[float] = None
    history: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def new(cls, intent: OrderIntent, now: datetime) -> "Order":
        return cls(
            id=uuid.uuid4().hex,
            intent=intent,
            state=OrderState.DRAFT,
            created_at=now,
            updated_at=now,
            history=[{"ts": now.isoformat(), "state": OrderState.DRAFT.value, "reason": "Created"}],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "intent": self.intent.to_dict(),
            "state": self.state.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "risk_failures": list(self.risk_failures),
            "risk_warnings": list(self.risk_warnings),
            "broker_order_id": self.broker_order_id,
            "filled_qty": self.filled_qty,
            "avg_fill_price": self.avg_fill_price,
            "history": list(self.history),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Order":
        return cls(
            id=d["id"],
            intent=OrderIntent.from_dict(d["intent"]),
            state=OrderState(d["state"]),
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
            risk_failures=list(d.get("risk_failures", [])),
            risk_warnings=list(d.get("risk_warnings", [])),
            broker_order_id=d.get("broker_order_id"),
            filled_qty=int(d.get("filled_qty", 0)),
            avg_fill_price=d.get("avg_fill_price"),
            history=list(d.get("history", [])),
        )
