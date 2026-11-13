"""Sample-size honesty for paper results (research display only; it never gates trading).

A win rate of 1/1 prints as 100%. This module attaches the context a reader needs before believing
any paper number: how many trades, how wide the uncertainty is, and how much of the total came from
one trade. It never labels a result as an edge. The thresholds are deliberately strict; raising the
bar is always allowed, lowering it needs the owner.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

MIN_TRADES_FOR_ANY_READING = 30  # below this the verdict is always INSUFFICIENT_SAMPLE
Z_95 = 1.959964


def wilson_interval(wins: int, n: int, z: float = Z_95) -> tuple[float, float] | None:
    """Wilson score interval for a proportion, in percent. None when there are no trades."""
    if n <= 0 or wins < 0 or wins > n:
        return None
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half) * 100, 1), round(min(1.0, centre + half) * 100, 1)


def summarize_evidence(pnls: Sequence[float], *, truncated: bool = False) -> dict[str, Any]:
    """Context for a list of closed-trade P&Ls (dollars). Non-finite values are excluded and counted."""
    clean = [float(p) for p in pnls if isinstance(p, (int, float)) and math.isfinite(p)]
    excluded = len(pnls) - len(clean)
    n = len(clean)
    wins = sum(1 for p in clean if p > 0)
    total = sum(clean)
    best = max(clean) if clean else None
    # Share of net P&L that one winning trade supplies; None unless the net is positive.
    top_share = round(best / total * 100, 1) if best is not None and best > 0 and total > 0 else None
    total_without_best = round(total - best, 2) if best is not None else None
    if n < MIN_TRADES_FOR_ANY_READING:
        verdict = "INSUFFICIENT_SAMPLE"
    elif truncated or excluded:
        verdict = "INCOMPLETE_DATA"
    elif total_without_best is not None and total_without_best <= 0 < total:
        verdict = "DEPENDS_ON_ONE_TRADE"
    else:
        verdict = "NO_CLAIM_PAPER_ONLY"  # enough trades to look at; still not evidence of an edge
    return {
        "trades": n,
        "min_trades_for_any_reading": MIN_TRADES_FOR_ANY_READING,
        "win_rate_95ci_pct": list(wilson_interval(wins, n)) if n else None,
        "top_trade_share_of_net_pct": top_share,
        "net_pnl_without_best_trade": total_without_best,
        "excluded_non_finite": excluded,
        "truncated": truncated,
        "verdict": verdict,
        "note": (
            "Verdict is about sample quality only. Paper fills are simulated, and no verdict here "
            "means a strategy has an edge."
        ),
    }
