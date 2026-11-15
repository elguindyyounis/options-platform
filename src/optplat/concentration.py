"""One-trade-story check for closed results (display-only, research).

A positive total can come from a single trade. This reports the realized total with the best
closed trade removed, so a reader can see that before trusting a headline. It changes nothing
that trades, and a small sample still proves nothing either way.
"""
from __future__ import annotations

from typing import Optional, Sequence

MIN_TRADES = 5  # below this the figures are shown but flagged as too thin to read


def one_trade_story(pnls: Sequence[Optional[float]]) -> dict:
    """`pnls` are closed-trade profits. Missing values (None) are ignored, never counted as zero."""
    xs = [float(p) for p in pnls if p is not None]
    n = len(xs)
    if n == 0:
        return {"closed": 0, "realized_ex_best": None, "best_pnl": None, "best_share_pct": None,
                "one_trade_story": None, "too_thin": True}
    total = sum(xs)
    best = max(xs)
    ex_best = total - best
    # Share of the total that the best trade supplies; only meaningful for a positive total.
    share = round(best / total * 100, 1) if total > 0 and best > 0 else None
    return {
        "closed": n,
        "realized_ex_best": round(ex_best, 2),
        "best_pnl": round(best, 2),
        "best_share_pct": share,
        # True when the total is positive but is not positive without the single best trade.
        "one_trade_story": bool(total > 0 and ex_best <= 0),
        "too_thin": n < MIN_TRADES,
    }
