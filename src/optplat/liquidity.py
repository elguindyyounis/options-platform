"""Research-only liquidity evidence for a proposed order. Display only: it never allows or blocks anything.

Reported volume and open interest are delayed and are NOT executable order-book depth. The exit
scenarios are illustrative bid-concession stress tests, not measured or realisable fill prices.
Idea adapted from the options-alerter's ``liquidity.py`` (participation caps and exit stress).
"""
from __future__ import annotations

import math
from typing import Any, Optional

PARTICIPATION_FLAG_PCT = 10.0  # alerter's cap: flag orders above 10% of reported volume or OI
SCENARIOS = (("BASE_BID", None), ("THIN_MARKET", 0.0), ("STRESSED_EXIT", 20.0))


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError, OverflowError):
        return None
    return v if math.isfinite(v) else None


def liquidity_evidence(
    *,
    bid: Any,
    ask: Any,
    volume: Any,
    open_interest: Any,
    quantity: int,
    multiplier: int = 100,
    slippage_pct: float = 0.5,
) -> dict[str, Any]:
    """Return participation flags and exit-stress scenarios. Unknown inputs are flagged, not assumed fine."""
    b, a = _num(bid), _num(ask)
    vol, oi = _num(volume), _num(open_interest)
    flags: list[str] = []
    valid = b is not None and a is not None and a > 0 and 0 <= b <= a
    spread = (a - b) / a * 100 if valid else None
    if not valid:
        flags.append("Invalid or missing two-sided quote")
    elif b <= 0:
        flags.append("Zero bid: exit price not observable")
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
        flags.append("Quantity must be a positive integer")
        quantity = 1

    vol_part = quantity / vol * 100 if vol and vol > 0 else None
    oi_part = quantity / oi * 100 if oi and oi > 0 else None
    if vol_part is None:
        flags.append("Reported volume missing or zero: exit depth unverified")
    elif vol_part > PARTICIPATION_FLAG_PCT:
        flags.append(f"Order is {vol_part:.0f}% of reported daily volume (flag above {PARTICIPATION_FLAG_PCT:.0f}%)")
    if oi_part is None:
        flags.append("Reported open interest missing or zero: depth unverified")
    elif oi_part > PARTICIPATION_FLAG_PCT:
        flags.append(f"Order is {oi_part:.0f}% of reported open interest (flag above {PARTICIPATION_FLAG_PCT:.0f}%)")

    scenarios: list[dict[str, Any]] = []
    if valid:
        entry = a * (1 + slippage_pct / 100) * multiplier * quantity
        extra = 0.0
        if spread is not None:
            extra += max(0.0, spread - 5) * 0.35
        # Missing volume/OI is treated as maximum participation (fail closed).
        extra += min(25.0, (quantity / vol if vol and vol > 0 else 1.0) * 70)
        extra += min(25.0, (quantity / oi if oi and oi > 0 else 1.0) * 35)
        extra = min(65.0, extra)
        for label, bump in SCENARIOS:
            concession = 0.5 if bump is None else extra if bump == 0.0 else min(95.0, extra + bump)
            proceeds = round(b * (100 - concession) / 100 * multiplier * quantity, 2)
            scenarios.append(
                {
                    "scenario": label,
                    "bid_concession_pct": round(concession, 2),
                    "modeled_exit_usd": proceeds,
                    "modeled_pnl_usd": round(proceeds - entry, 2),
                }
            )
    return {
        "status": "SCENARIO_ONLY",
        "spread_pct": round(spread, 2) if spread is not None else None,
        "volume_participation_pct": round(vol_part, 2) if vol_part is not None else None,
        "oi_participation_pct": round(oi_part, 2) if oi_part is not None else None,
        "flags": flags,
        "exit_scenarios": scenarios,
        "limits": "Reported volume/OI are not live depth; scenarios are illustrative, not realisable prices.",
    }
