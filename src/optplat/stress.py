"""Research-only exit-friction stress for an open long option. Display/analysis only.

The simulated broker sells at bid minus a flat slippage. A real exit from a wide market is often
worse than that. These scenarios show how much of a paper result survives extra bid concession.
They are illustrative assumptions, not measured depth, and are never used to place or size orders.
Idea borrowed from the alerter's liquidity.exit_stress (spread-based part only; this platform's
quotes carry no volume or open interest).
"""
from __future__ import annotations

import math
from typing import Any

from .models import Position, Quote

# (label, extra concession on top of flat slippage, as % of bid). Fixed, deliberately simple.
STRESS_NOTE = (
    "Illustrative bid-concession scenarios, not measured depth or a realizable fill price. "
    "Paper results prove nothing about live trading."
)


def spread_concession_pct(spread_pct_of_ask: float) -> float:
    """Extra bid concession: 0.35% of bid per spread point above 5%, capped at 65%."""
    if not math.isfinite(spread_pct_of_ask):
        return 65.0
    return min(65.0, max(0.0, spread_pct_of_ask - 5.0) * 0.35)


def exit_stress(position: Position, quote: Quote, slippage_pct: float = 0.5) -> dict[str, Any]:
    """Modeled P&L if the position were sold under three bid-concession severities.

    Fail closed: an invalid quote or unusable cost basis returns ``available: False``.
    """
    if not quote.is_valid() or quote.contract != position.contract:
        return {"available": False, "reason": "No valid quote for the held contract", "note": STRESS_NOTE}
    if not (math.isfinite(position.avg_cost) and position.avg_cost > 0 and position.quantity > 0):
        return {"available": False, "reason": "Cost basis unavailable", "note": STRESS_NOTE}
    slip = min(max(float(slippage_pct), 0.0), 3.0)
    extra = spread_concession_pct(quote.spread_pct_of_ask())
    mult = position.contract.multiplier
    cost = position.avg_cost * mult * position.quantity
    scenarios = []
    for label, concession in (
        ("SIM_FILL", 0.0),
        ("WIDE_MARKET", extra),
        ("STRESSED_EXIT", min(95.0, extra + 20.0)),
    ):
        price = max(0.0, quote.bid * (1 - slip / 100) * (1 - concession / 100))
        proceeds = round(price * mult * position.quantity, 2)
        scenarios.append({
            "scenario": label,
            "extra_concession_pct": round(concession, 2),
            "exit_price": round(price, 4),
            "pnl_usd": round(proceeds - cost, 2),
            "return_pct": round((proceeds / cost - 1) * 100, 2),
        })
    return {
        "available": True,
        "spread_pct": round(quote.spread_pct_of_ask(), 2),
        "scenarios": scenarios,
        "note": STRESS_NOTE,
    }
