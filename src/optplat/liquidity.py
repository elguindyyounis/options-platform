"""Liquidity tiers and an exit-friction stress test for simulated option trades.

Ported in idea from the options-alerter repo (``liquidity.py`` and ``exit_decisions.py``), rewritten here with this platform's
types and fail-closed habits. Both are scenario tools for research lanes: open interest and volume are not an order book, and a
stressed exit price is a pessimistic what-if, never a price anyone could have traded at.
"""
from __future__ import annotations

from typing import Any, Optional

BASE_SLIPPAGE_PCT = 0.5
MAX_CONCESSION_PCT = 40.0
WIDE_SPREAD_FREE_PCT = 15.0  # spread beyond this starts to cost extra on the way out


def liquidity_tier(volume: Optional[int], open_interest: Optional[int], spread_pct: Optional[float]) -> str:
    """PREFERRED / WATCH / THIN. Anything missing is THIN: unknown depth is treated as no depth."""
    if volume is None or open_interest is None or spread_pct is None:
        return "THIN"
    if volume >= 100 and open_interest >= 500 and spread_pct <= 10:
        return "PREFERRED"
    if volume >= 10 and open_interest >= 50 and spread_pct <= 20:
        return "WATCH"
    return "THIN"


def exit_concession_pct(quantity: int, volume: Optional[int], open_interest: Optional[int], spread_pct: Optional[float]) -> float:
    """Extra percent knocked off the bid to model a less friendly exit. Larger when the spread is wide or the size is big
    compared with the day's volume and open interest. Missing data costs the maximum, not zero."""
    if spread_pct is None or volume is None or open_interest is None:
        return MAX_CONCESSION_PCT
    qty = max(1, int(quantity))
    penalty = min(30.0, max(0.0, spread_pct - WIDE_SPREAD_FREE_PCT) * 0.25
                  + min(10.0, qty / max(1, volume) * 12) + min(8.0, qty / max(1, open_interest) * 6))
    return round(min(MAX_CONCESSION_PCT, BASE_SLIPPAGE_PCT + penalty), 2)


def stress_exit(bid: float, quantity: int, volume: Optional[int], open_interest: Optional[int], spread_pct: Optional[float]) -> dict[str, Any]:
    pct = exit_concession_pct(quantity, volume, open_interest, spread_pct)
    return {"concession_pct": pct, "price": round(max(0.0, bid * (1 - pct / 100)), 2)}
