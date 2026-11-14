"""Research-only check: how optimistic is a simulated fill likely to be?

The sim broker fills the whole order at the touch (ask plus slippage). A real market maker shows
limited size, so a large order against thin volume or open interest would not fill like that.
This module only LABELS an entry; it never blocks, resizes, or changes an order.
Missing or unparseable volume/OI is treated as unverified, never as fine.
"""
from __future__ import annotations

from typing import Any, Optional

PARTICIPATION_LIMIT = 0.10  # flag orders above 10% of reported daily volume or open interest


def _count(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value < 0 or value in (float("inf"),):
        return None
    return int(value)


def fill_realism(quantity: Any, volume: Any, open_interest: Any) -> dict[str, Any]:
    """Return tags describing why a simulated full fill at the touch may be too kind."""
    tags: list[str] = []
    qty = _count(quantity)
    vol = _count(volume)
    oi = _count(open_interest)
    if qty is None or qty < 1:
        tags.append("QUANTITY_UNKNOWN")
    if vol is None:
        tags.append("VOLUME_UNVERIFIED")
    if oi is None:
        tags.append("OI_UNVERIFIED")
    if qty and qty >= 1:
        if vol is not None and qty > max(1, int(vol * PARTICIPATION_LIMIT)):
            tags.append("EXCEEDS_10PCT_OF_VOLUME")
        if oi is not None and qty > max(1, int(oi * PARTICIPATION_LIMIT)):
            tags.append("EXCEEDS_10PCT_OF_OPEN_INTEREST")
    return {
        "tags": tags,
        "sim_fill_may_be_optimistic": bool(tags),
        "volume": vol,
        "open_interest": oi,
        "note": "Label only. The sim fills the full size at the touch; real depth is not verified.",
    }
