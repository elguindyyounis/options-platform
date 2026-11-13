"""Research-only exit-liquidity stress for long options. Display/analysis only: it never trades.

The simulated broker sells at bid minus a flat slippage, whatever the spread or size. That is
optimistic for wide spreads, thin contracts, and multi-contract orders. This module re-prices a
liquidation under harsher, clearly hypothetical bid concessions so reports can show how much of a
paper result survives. The concession formula is a deliberately rough heuristic, NOT calibrated on
order-book data, and the outputs are scenarios, not executable prices.

Idea borrowed from the owner's options-alerter ``liquidity.exit_stress``; re-implemented here with
fail-closed handling: unknown volume/open interest is treated as the worst depth, never as fine.
"""
from __future__ import annotations

import math
from typing import Any, Optional

MAX_CONCESSION_PCT = 95.0
WARNING = "Illustrative bid-concession stress, not measured depth or a realizable fill price."


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _ok(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def extra_concession_pct(
    spread_pct: float, quantity: int, volume: Optional[float], open_interest: Optional[float]
) -> float:
    """Extra % taken off the bid. Spread beyond 5% of ask, plus size vs volume and open interest.

    Missing/invalid volume or OI counts as one contract of depth, so the size terms hit their caps.
    """
    vol = max(1.0, float(volume)) if _ok(volume) and volume > 0 else 1.0
    oi = max(1.0, float(open_interest)) if _ok(open_interest) and open_interest > 0 else 1.0
    participation = quantity / vol
    concentration = quantity / oi
    extra = (
        max(0.0, spread_pct - 5.0) * 0.35
        + min(25.0, participation * 70.0)
        + min(25.0, concentration * 35.0)
    )
    return _clamp(extra, 0.0, 65.0)


def exit_stress(
    *,
    entry_fill: float,
    bid: float,
    ask: float,
    quantity: int,
    multiplier: int = 100,
    volume: Optional[float] = None,
    open_interest: Optional[float] = None,
    slippage_pct: float = 0.5,
) -> Optional[dict[str, Any]]:
    """Re-price liquidating ``quantity`` contracts bought at ``entry_fill``. None if inputs are unusable."""
    if not all(_ok(v) for v in (entry_fill, bid, ask, slippage_pct)):
        return None
    if entry_fill <= 0 or ask <= 0 or not (0 <= bid <= ask) or quantity < 1 or multiplier < 1:
        return None
    spread_pct = (ask - bid) / ask * 100
    extra = extra_concession_pct(spread_pct, quantity, volume, open_interest)
    cost = entry_fill * multiplier * quantity
    scenarios = []
    for label, concession in (
        ("SIM_ASSUMPTION", float(slippage_pct)),
        ("THIN_MARKET", _clamp(slippage_pct + extra, 0.0, MAX_CONCESSION_PCT)),
        ("STRESSED_EXIT", _clamp(slippage_pct + extra + 20.0, 0.0, MAX_CONCESSION_PCT)),
    ):
        proceeds = max(0.0, bid * (1 - concession / 100)) * multiplier * quantity
        scenarios.append(
            {
                "scenario": label,
                "bid_concession_pct": round(concession, 2),
                "modeled_exit_usd": round(proceeds, 2),
                "modeled_pnl_usd": round(proceeds - cost, 2),
                "premium_return_pct": round((proceeds / cost - 1) * 100, 2),
            }
        )
    return {
        "spread_pct": round(spread_pct, 2),
        "depth_known": _ok(volume) and _ok(open_interest) and volume > 0 and open_interest > 0,
        "entry_cost_usd": round(cost, 2),
        "scenarios": scenarios,
        "warning": WARNING,
    }
