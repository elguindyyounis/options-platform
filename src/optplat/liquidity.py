"""Research-only liquidity review for a proposed entry.

DISPLAY ONLY. Nothing here gates, sizes or changes an order. Reported volume and open interest are
delayed and are not order-book depth, and the exit scenarios are illustrative concessions to the bid,
not measured fills. Idea borrowed from the alerter's ``liquidity.exit_stress`` (see
``docs/COMPARISON_ALERTER.md``); the code and constants here are this repo's own.
"""
from __future__ import annotations

import math
from typing import Any, Optional

PARTICIPATION_WARN = 0.10  # same 10% yardstick the alerter uses as a hard entry gate
LIMITS = (
    "Reported volume/OI are delayed and are not executable depth; scenarios are illustrative "
    "bid concessions, not measured fills. Display only: no order is gated or sized by this."
)


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def entry_liquidity_review(
    *,
    quantity: int,
    volume: Any,
    open_interest: Any,
    bid: Any,
    ask: Any,
    limit_price: Any,
    multiplier: int = 100,
) -> dict[str, Any]:
    """Participation versus reported volume/OI plus a bid-liquidation stress, round trip."""
    qty = quantity if isinstance(quantity, int) and quantity > 0 else 0
    vol, oi = _num(volume), _num(open_interest)
    b, a, lim = _num(bid), _num(ask), _num(limit_price)
    flags: list[str] = []
    out: dict[str, Any] = {"quantity": qty, "scenarios": [], "flags": flags, "limits": LIMITS}

    if qty == 0:
        flags.append("Quantity is not a positive integer")
    part_vol = qty / vol if vol and vol > 0 and qty else None
    part_oi = qty / oi if oi and oi > 0 and qty else None
    out["participation_of_volume"] = None if part_vol is None else round(part_vol, 4)
    out["participation_of_open_interest"] = None if part_oi is None else round(part_oi, 4)
    if part_vol is None:
        flags.append("Reported volume missing or zero: participation unknown")
    elif part_vol > PARTICIPATION_WARN:
        flags.append(f"Order is {part_vol:.0%} of reported daily volume (>10%)")
    if part_oi is None:
        flags.append("Reported open interest missing or zero: participation unknown")
    elif part_oi > PARTICIPATION_WARN:
        flags.append(f"Order is {part_oi:.0%} of reported open interest (>10%)")

    if None in (b, a, lim) or a <= 0 or lim <= 0 or b < 0 or b > a or not qty:
        flags.append("No valid two-sided quote: exit scenarios not computed")
        return out

    spread = (a - b) / a * 100
    # Heuristic, not fitted to any fills: wider spread and bigger share of the day's volume/OI
    # both push the assumed exit further below the bid. Unknown depth is treated as worst case.
    extra = max(0.0, spread - 5) * 0.35
    extra += 25.0 if part_vol is None else min(25.0, part_vol * 70)
    extra += 25.0 if part_oi is None else min(25.0, part_oi * 35)
    extra = min(extra, 65.0)
    cost = lim * multiplier * qty
    for label, concession in (("BASE_BID", 0.0), ("THIN_MARKET", extra), ("STRESSED_EXIT", min(95.0, extra + 20))):
        proceeds = b * (1 - concession / 100) * multiplier * qty
        out["scenarios"].append(
            {
                "scenario": label,
                "bid_concession_pct": round(concession, 2),
                "modeled_exit_usd": round(proceeds, 2),
                "modeled_pnl_usd": round(proceeds - cost, 2),
                "modeled_return_pct": round((proceeds / cost - 1) * 100, 2),
            }
        )
    out["entry_cost_usd"] = round(cost, 2)
    out["spread_pct_of_ask"] = round(spread, 2)
    return out
