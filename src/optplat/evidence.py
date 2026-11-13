"""Display-only evidence labels for paper results.

Nothing here changes what is traded. It exists so a handful of lucky (or unlucky) paper trades
cannot be read as a result. The minimum sample is a labelling threshold, not a risk control.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

MIN_CLOSED_TRADES = 30  # below this, results are labelled INSUFFICIENT_SAMPLE
WILSON_Z = 1.96  # ~95% interval


def wilson_interval(wins: int, n: int) -> tuple[float, float] | None:
    """95% Wilson score interval for a win rate, in percent. None when n == 0."""
    if n <= 0 or wins < 0 or wins > n:
        return None
    p = wins / n
    z2 = WILSON_Z**2
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = WILSON_Z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)


def assess_results(pnls: Sequence[float]) -> dict[str, Any]:
    """Label a list of closed-trade P&L values. Fail-closed: anything doubtful is not a 'result'."""
    clean = [float(p) for p in pnls if isinstance(p, (int, float)) and math.isfinite(p)]
    n = len(clean)
    wins = sum(1 for p in clean if p > 0)
    total = sum(clean)
    interval = wilson_interval(wins, n)
    ex_best = round(total - max(clean), 2) if n else None
    # "Best trade carries the result": profitable overall, but not without its single best trade.
    depends_on_best = bool(n >= 2 and total > 0 and ex_best is not None and ex_best <= 0)
    sufficient = n >= MIN_CLOSED_TRADES
    notes: list[str] = []
    if not sufficient:
        notes.append(f"Only {n} closed trades; at least {MIN_CLOSED_TRADES} are needed before any figure is called a result.")
    if depends_on_best:
        notes.append("Total P&L is positive only because of the single best trade.")
    if interval is not None:
        notes.append(f"Win rate 95% interval {interval[0]}%-{interval[1]}%.")
    notes.append("Simulated fills and no out-of-sample split: even a sufficient sample does not show an edge.")
    return {
        "status": "SUFFICIENT_SAMPLE_UNVALIDATED" if sufficient else "INSUFFICIENT_SAMPLE",
        "closed_trades": n,
        "min_closed_trades": MIN_CLOSED_TRADES,
        "win_rate_interval_pct": list(interval) if interval else None,
        "pnl_excluding_best_trade": ex_best,
        "depends_on_best_trade": depends_on_best,
        "notes": notes,
    }
