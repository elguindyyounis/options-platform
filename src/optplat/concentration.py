"""One-trade-story check for closed results (display-only, research).

A positive total can come from a single trade. This reports the realized total with the best
closed trade removed, so a reader can see that before trusting a headline. It changes nothing
that trades, and a small sample still proves nothing either way.
"""
from __future__ import annotations

from typing import Optional, Sequence

MIN_TRADES = 5  # below this the figures are shown but flagged as too thin to read
# A trade whose size was more than this share of the contract's reported daily volume, or open interest, is
# "oversized": a real order that big would probably have moved the price or not filled. The same cut-offs tag
# OVERSIZED_FOR_LIQUIDITY in post-mortems. (The alerter blocks entries above 10% of both; 5% here for OI is stricter.)
OVERSIZE_VOLUME_PCT = 10.0
OVERSIZE_OI_PCT = 5.0


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


def is_oversized(size_vs_volume_pct: Optional[float], size_vs_oi_pct: Optional[float]) -> Optional[bool]:
    """True/False when the size was recorded; None when neither figure is known (never assumed fine)."""
    if size_vs_volume_pct is None and size_vs_oi_pct is None:
        return None
    return bool((size_vs_volume_pct or 0) > OVERSIZE_VOLUME_PCT or (size_vs_oi_pct or 0) > OVERSIZE_OI_PCT)


def liquidity_split(rows: Sequence[tuple]) -> dict:
    """`rows` are (pnl, size_vs_volume_pct, size_vs_oi_pct) for closed trades. Splits realized P&L by whether the
    simulated size was realistic for the contract. Trades with no recorded size are kept apart as unknown, never
    counted as within limits. `positive_only_if_oversized` is True when the total is positive but the trades
    that were realistically sized did not make money, so the headline leans on fills a real market may not give."""
    groups = {"oversized": [], "within_limits": [], "unknown": []}
    for pnl, vol, oi in rows:
        if pnl is None:
            continue
        flag = is_oversized(vol, oi)
        groups["unknown" if flag is None else "oversized" if flag else "within_limits"].append(float(pnl))
    total = sum(sum(v) for v in groups.values())
    n = sum(len(v) for v in groups.values())
    out = {"closed": n, **{f"{k}_trades": len(v) for k, v in groups.items()},
           **{f"{k}_pnl": round(sum(v), 2) if v else None for k, v in groups.items()}}
    out["positive_only_if_oversized"] = bool(groups["oversized"] and total > 0 and sum(groups["within_limits"]) <= 0)
    return out
