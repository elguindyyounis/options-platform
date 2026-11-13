"""Display-only liquidity tags for simulated entries.

The simulated broker fills any quantity at ask plus slippage, whatever the contract's volume or
open interest. A paper fill that would be 40% of a day's volume would never happen in real life, so
results built on such fills look better than they are. These tags make that visible. They do NOT
block, resize, or otherwise change any order. Participation is measured against *reported* volume
and open interest, which can be delayed and are not order-book depth.
"""
from __future__ import annotations

import math
from typing import Any, Optional

MAX_PARTICIPATION = 0.10  # same 10% yardstick the sister alerter project applies to its entries


def _finite_nonneg(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


def participation_tags(quantity: int, volume: Any, open_interest: Any) -> dict[str, Any]:
    """Tag an entry by its size relative to reported volume and open interest. Fail-closed: unknown
    volume or OI is reported as ``unknown`` and flagged, never assumed fine."""
    vol = _finite_nonneg(volume)
    oi = _finite_nonneg(open_interest)
    qty = int(quantity)
    flags: list[str] = []
    out: dict[str, Any] = {"quantity": qty, "status": "SCENARIO_ONLY"}
    for label, base in (("volume", vol), ("open_interest", oi)):
        if base is None or base <= 0:
            out[f"pct_of_{label}"] = None
            flags.append(f"{label} unknown or zero")
            continue
        pct = round(qty / base * 100, 2)
        out[f"pct_of_{label}"] = pct
        if qty / base > MAX_PARTICIPATION + 1e-12:
            flags.append(f"{qty} contracts is {pct:.1f}% of reported {label} (> {MAX_PARTICIPATION:.0%})")
    out["flags"] = flags
    out["fill_realism"] = "QUESTIONABLE" if flags else "WITHIN_10PCT"
    out["note"] = "Display only. Reported volume/OI are not order-book depth; the sim fills any size."
    return out
