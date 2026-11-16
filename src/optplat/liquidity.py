"""Display-only size-versus-liquidity note for a proposed entry.

Modelled on the alerter's ``liquidity.py`` check (quantity above 10% of reported daily volume or
open interest). It only describes; it never blocks, resizes or changes an order. Volume and open
interest are provider-reported, often delayed, and are not live executable depth.
"""
from __future__ import annotations

from typing import Any, Optional

PARTICIPATION_LIMIT = 0.10


def size_vs_liquidity(quantity: int, volume: Optional[int], open_interest: Optional[int]) -> dict[str, Any]:
    """Return how large ``quantity`` is against reported volume and open interest."""
    def share(denominator: Optional[int]) -> Optional[float]:
        if denominator is None or denominator <= 0 or quantity < 1:
            return None
        return round(quantity / denominator * 100, 2)

    vol_pct, oi_pct = share(volume), share(open_interest)
    warnings: list[str] = []
    if vol_pct is None:
        warnings.append("daily volume not reported or zero; exit depth unknown")
    elif vol_pct > PARTICIPATION_LIMIT * 100:
        warnings.append(f"{quantity} contract(s) is {vol_pct}% of reported daily volume (over 10%)")
    if oi_pct is None:
        warnings.append("open interest not reported or zero; exit depth unknown")
    elif oi_pct > PARTICIPATION_LIMIT * 100:
        warnings.append(f"{quantity} contract(s) is {oi_pct}% of reported open interest (over 10%)")
    return {
        "quantity": quantity,
        "pct_of_volume": vol_pct,
        "pct_of_open_interest": oi_pct,
        "warnings": warnings,
        "note": "Display only. Reported volume/OI are not live executable depth; paper fills ignore size impact.",
    }
