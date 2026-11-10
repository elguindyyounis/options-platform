"""Deterministic, fail-closed risk policy. No model, score or setting outside the policy can waive it."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Sequence

from .models import Account, OrderIntent, Position, Quote, Side


@dataclass(frozen=True)
class RiskPolicy:
    version: str = "risk-v1"
    max_position_pct: float = 1.0          # worst-case premium per new order, % of equity
    max_total_premium_pct: float = 10.0    # open premium + this order, % of equity
    max_spread_pct_of_ask: float = 15.0
    max_quote_age_s: int = 60
    max_clock_skew_s: int = 5
    max_limit_over_ask_pct: float = 1.0    # a buy limit may not exceed ask by more than this
    max_limit_under_bid_pct: float = 3.0   # a sell limit may not undercut the bid by more than this
    max_quantity: int = 100
    min_dte: int = 7
    max_dte: int = 730
    max_open_positions: int = 12
    max_same_underlying_side: int = 2      # open contracts per underlying and call/put direction
    require_verified_quote_time: bool = True

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    worst_case_cost: Optional[float] = None
    policy_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "failures": list(self.failures),
            "warnings": list(self.warnings),
            "worst_case_cost": self.worst_case_cost,
            "policy_version": self.policy_version,
        }


def evaluate(
    intent: OrderIntent,
    quote: Optional[Quote],
    account: Account,
    positions: Sequence[Position],
    policy: RiskPolicy,
    *,
    now: datetime,
    kill_switch: bool = False,
    pending_close_qty: int = 0,
) -> RiskDecision:
    """Dispatch on order side. The kill switch blocks new risk (buys) but never blocks closing it."""
    if intent.side is Side.SELL_TO_CLOSE:
        return _evaluate_sell(intent, quote, positions, policy, now=now, pending_close_qty=pending_close_qty)
    return _evaluate_buy(intent, quote, account, positions, policy, now=now, kill_switch=kill_switch)


def _evaluate_buy(
    intent: OrderIntent,
    quote: Optional[Quote],
    account: Account,
    positions: Sequence[Position],
    policy: RiskPolicy,
    *,
    now: datetime,
    kill_switch: bool = False,
) -> RiskDecision:
    failures: list[str] = []
    warnings: list[str] = []
    contract = intent.contract

    if kill_switch:
        failures.append("Kill switch is active")

    qty = intent.quantity
    qty_ok = type(qty) is int and 1 <= qty <= policy.max_quantity
    if not qty_ok:
        failures.append(f"Quantity must be an integer between 1 and {policy.max_quantity}")

    price = intent.limit_price
    price_ok = (
        isinstance(price, (int, float))
        and not isinstance(price, bool)
        and math.isfinite(price)
        and price > 0
    )
    if not price_ok:
        failures.append("Limit price must be a positive, finite number")

    if contract.multiplier != 100:
        failures.append("Only standard 100-share contracts are supported")

    dte = (contract.expiry - now.date()).days
    if not policy.min_dte <= dte <= policy.max_dte:
        failures.append(f"Days to expiry {dte} outside {policy.min_dte}-{policy.max_dte}")

    if quote is None:
        failures.append("No broker quote available")
    else:
        if quote.contract != contract:
            failures.append("Quote is for a different contract")
        if not quote.is_valid():
            failures.append("Invalid two-sided quote")
        else:
            if quote.bid <= 0:
                failures.append("Zero bid: exit price not observable")
            spread = quote.spread_pct_of_ask()
            if spread > policy.max_spread_pct_of_ask:
                failures.append(
                    f"Spread {spread:.1f}% of ask exceeds {policy.max_spread_pct_of_ask:.0f}% limit"
                )
            if price_ok and price > quote.ask * (1 + policy.max_limit_over_ask_pct / 100) + 1e-9:
                failures.append("Limit price exceeds the ask by more than the allowed margin")
        age = quote.age_seconds(now)
        if age < -policy.max_clock_skew_s or age > policy.max_quote_age_s:
            failures.append(f"Quote is stale or from the future (age {age:.0f}s)")
        if policy.require_verified_quote_time and not quote.timestamp_verified:
            failures.append("Quote time is not verified by the broker or venue")

    cost: Optional[float] = None
    if qty_ok and price_ok:
        cost = round(price * contract.multiplier * qty, 2)

    if not (math.isfinite(account.equity) and account.equity > 0):
        failures.append("Account equity unavailable or non-positive")
    elif cost is not None:
        if cost > account.equity * policy.max_position_pct / 100:
            failures.append("Exceeds per-position premium limit")
        if account.open_premium + cost > account.equity * policy.max_total_premium_pct / 100:
            failures.append("Exceeds aggregate open premium limit")
    if cost is not None and cost > account.cash:
        failures.append("Insufficient cash")

    if len(positions) >= policy.max_open_positions:
        failures.append("Maximum open positions reached")
    if any(p.contract == contract for p in positions):
        failures.append("Duplicate open contract")
    same_side = sum(
        1
        for p in positions
        if p.contract.underlying == contract.underlying and p.contract.right is contract.right
    )
    if same_side >= policy.max_same_underlying_side:
        failures.append(
            f"Already holding {same_side} {contract.underlying} {contract.right.name.lower()} position(s): concentration limit"
        )

    return RiskDecision(
        allowed=not failures,
        failures=failures,
        warnings=warnings,
        worst_case_cost=cost,
        policy_version=policy.version,
    )


def _evaluate_sell(
    intent: OrderIntent,
    quote: Optional[Quote],
    positions: Sequence[Position],
    policy: RiskPolicy,
    *,
    now: datetime,
    pending_close_qty: int,
) -> RiskDecision:
    failures: list[str] = []
    warnings: list[str] = []
    contract = intent.contract

    qty = intent.quantity
    qty_ok = type(qty) is int and 1 <= qty <= policy.max_quantity
    if not qty_ok:
        failures.append(f"Quantity must be an integer between 1 and {policy.max_quantity}")

    price = intent.limit_price
    price_ok = (
        isinstance(price, (int, float))
        and not isinstance(price, bool)
        and math.isfinite(price)
        and price > 0
    )
    if not price_ok:
        failures.append("Limit price must be a positive, finite number")

    held = sum(p.quantity for p in positions if p.contract == contract)
    if qty_ok and held - pending_close_qty < qty:
        failures.append(
            f"Not enough open position to close (held {held}, already being closed {pending_close_qty})"
        )

    if contract.expiry < now.date():
        failures.append("Contract has expired")

    if quote is None:
        failures.append("No broker quote available")
    else:
        if quote.contract != contract:
            failures.append("Quote is for a different contract")
        if not quote.is_valid():
            failures.append("Invalid two-sided quote")
        else:
            if quote.bid <= 0:
                failures.append("Zero bid: exit price not observable")
            elif price_ok and price < quote.bid * (1 - policy.max_limit_under_bid_pct / 100) - 1e-9:
                failures.append("Limit price undercuts the bid by more than the allowed margin")
            if quote.spread_pct_of_ask() > policy.max_spread_pct_of_ask:
                warnings.append("Wide spread: exit may be costly")
        age = quote.age_seconds(now)
        if age < -policy.max_clock_skew_s or age > policy.max_quote_age_s:
            failures.append(f"Quote is stale or from the future (age {age:.0f}s)")
        if policy.require_verified_quote_time and not quote.timestamp_verified:
            failures.append("Quote time is not verified by the broker or venue")

    return RiskDecision(
        allowed=not failures,
        failures=failures,
        warnings=warnings,
        worst_case_cost=None,
        policy_version=policy.version,
    )
