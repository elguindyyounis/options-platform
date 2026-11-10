"""Exit rules for open long options. Pure functions: they decide, they never trade."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .models import Position, Quote

HOLD = "HOLD"
EXIT = "EXIT"
UNOBSERVABLE = "UNOBSERVABLE"


@dataclass(frozen=True)
class ExitPolicy:
    take_profit_pct: float = 40.0
    stop_loss_pct: float = 30.0
    max_days_held: int = 0        # 0 disables the time stop
    min_dte_to_hold: int = 5      # leave positions before expiry gets dangerous
    max_quote_age_s: int = 60


@dataclass(frozen=True)
class ExitDecision:
    action: str
    reason: str
    pnl_pct: Optional[float] = None
    trigger: Optional[str] = None


def evaluate_exit(
    position: Position,
    quote: Optional[Quote],
    *,
    entry_time: Optional[datetime],
    now: datetime,
    policy: ExitPolicy,
) -> ExitDecision:
    """A missing, crossed, zero-bid or stale quote is UNOBSERVABLE, never a silent HOLD."""
    if quote is None:
        return ExitDecision(UNOBSERVABLE, "No quote for the held contract")
    if quote.contract != position.contract:
        return ExitDecision(UNOBSERVABLE, "Quote is for a different contract")
    if not quote.is_valid() or quote.bid <= 0:
        return ExitDecision(UNOBSERVABLE, "Quote invalid or zero bid: exit price not observable")
    age = quote.age_seconds(now)
    if age > policy.max_quote_age_s or age < -policy.max_quote_age_s:
        return ExitDecision(UNOBSERVABLE, f"Quote is stale (age {age:.0f}s)")
    if not (math.isfinite(position.avg_cost) and position.avg_cost > 0):
        return ExitDecision(UNOBSERVABLE, "Position cost basis unavailable")

    pnl_pct = round((quote.bid - position.avg_cost) / position.avg_cost * 100, 2)
    dte = (position.contract.expiry - now.date()).days

    if dte <= policy.min_dte_to_hold:
        return ExitDecision(EXIT, f"{dte} days to expiry", pnl_pct, "expiry_window")
    if pnl_pct <= -policy.stop_loss_pct:
        return ExitDecision(EXIT, f"Stop loss at {pnl_pct}%", pnl_pct, "stop_loss")
    if pnl_pct >= policy.take_profit_pct:
        return ExitDecision(EXIT, f"Take profit at {pnl_pct}%", pnl_pct, "take_profit")
    if policy.max_days_held > 0 and entry_time is not None:
        held_days = (now - entry_time).total_seconds() / 86400
        if held_days >= policy.max_days_held:
            return ExitDecision(EXIT, f"Held {held_days:.1f} days", pnl_pct, "max_days_held")
    return ExitDecision(HOLD, "No exit rule triggered", pnl_pct)
