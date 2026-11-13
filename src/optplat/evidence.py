"""Sample-size honesty for paper results. Pure functions; they never trade.

A win rate from a handful of simulated trades is noise. These helpers attach an uncertainty
interval and a verdict so a tiny sample can never read as a result. Nothing here proves an edge.
"""
from __future__ import annotations

import math
from typing import Any, Optional

# Below this many closed trades the numbers are labelled anecdotes. A research threshold only:
# it gates labels, not trading, and passing it still proves nothing about an edge.
MIN_TRADES_FOR_RESULT = 30

INSUFFICIENT = "INSUFFICIENT_SAMPLE"
ENOUGH_TO_EXAMINE = "ENOUGH_TO_EXAMINE"


def wilson_interval(wins: int, n: int, z: float = 1.96) -> Optional[tuple[float, float]]:
    """95% Wilson score interval for a win rate, in percent. None when n is 0 or inputs invalid."""
    if n <= 0 or wins < 0 or wins > n:
        return None
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)


def evidence_summary(pnls: list[float]) -> dict[str, Any]:
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    ci = wilson_interval(wins, n)
    verdict = ENOUGH_TO_EXAMINE if n >= MIN_TRADES_FOR_RESULT else INSUFFICIENT
    return {
        "sample_verdict": verdict,
        "min_trades_for_result": MIN_TRADES_FOR_RESULT,
        "win_rate_ci95_pct": list(ci) if ci else None,
        "evidence_note": (
            f"Only {n} closed trade(s); fewer than {MIN_TRADES_FOR_RESULT}. Treat as an anecdote, not a result."
            if verdict == INSUFFICIENT
            else "Sample size alone does not show an edge: fills are simulated and quote times unverified."
        ),
    }
