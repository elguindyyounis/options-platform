"""Small-sample honesty helpers for paper results. Display-only: nothing here gates a trade."""
from __future__ import annotations

import math
from typing import Optional

# Below this many closed trades the report labels results INSUFFICIENT_SAMPLE.
# This is a labelling threshold for display, not a statistical guarantee of an edge.
MIN_TRADES_FOR_READING = 30
Z95 = 1.959964


def wilson_interval_pct(wins: int, n: int) -> Optional[tuple[float, float]]:
    """95% Wilson score interval for a win rate, in percent. None when n == 0."""
    if n <= 0 or wins < 0 or wins > n:
        return None
    p = wins / n
    denom = 1 + Z95 ** 2 / n
    centre = (p + Z95 ** 2 / (2 * n)) / denom
    half = Z95 * math.sqrt(p * (1 - p) / n + Z95 ** 2 / (4 * n ** 2)) / denom
    return round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)


def sample_assessment(pnls: list[float]) -> dict:
    """Describe how much (little) a list of closed-trade P&Ls can say."""
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    interval = wilson_interval_pct(wins, n)
    status = "NO_TRADES" if n == 0 else (
        "INSUFFICIENT_SAMPLE" if n < MIN_TRADES_FOR_READING else "DESCRIPTIVE_ONLY")
    best = max(pnls) if pnls else None
    return {
        "status": status,
        "closed_trades": n,
        "min_trades_for_reading": MIN_TRADES_FOR_READING,
        "win_rate_ci95_pct": list(interval) if interval else None,
        "realized_pnl_without_best_trade": round(sum(pnls) - best, 2) if best is not None else None,
        "note": "Even DESCRIPTIVE_ONLY is paper data with simulated fills; it is not evidence of an edge.",
    }
