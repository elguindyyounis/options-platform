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


MAX_GROUPS = 25  # groups listed per split; the totals and flags always use every group


def group_story(pairs: Sequence[tuple]) -> dict:
    """`pairs` are (group_key, pnl) for closed trades. Splits realized P&L by group (underlying, or close day)
    and says whether a positive total is positive only because of the single best group. A missing key is its own
    "unknown" group, never dropped. Missing pnl is ignored, never counted as zero. Display-only."""
    totals: dict[str, list[float]] = {}
    for key, pnl in pairs:
        if pnl is None:
            continue
        totals.setdefault(str(key) if key else "unknown", []).append(float(pnl))
    n_groups = len(totals)
    if n_groups == 0:
        return {"groups": [], "group_count": 0, "closed": 0, "realized_ex_best_group": None, "best_group": None,
                "best_group_share_pct": None, "one_group_story": None, "too_thin": True}
    rows = sorted(({"group": k, "closed": len(v), "pnl": round(sum(v), 2)} for k, v in totals.items()),
                  key=lambda r: (-r["pnl"], r["group"]))
    total = sum(sum(v) for v in totals.values())
    best = rows[0]
    ex_best = total - best["pnl"]
    share = round(best["pnl"] / total * 100, 1) if total > 0 and best["pnl"] > 0 else None
    return {
        "groups": rows[:MAX_GROUPS], "group_count": n_groups, "closed": sum(len(v) for v in totals.values()),
        "realized_ex_best_group": round(ex_best, 2), "best_group": best["group"], "best_group_share_pct": share,
        # True when the total is positive but is not positive without the single best group.
        "one_group_story": bool(total > 0 and ex_best <= 0),
        # Fewer than 3 groups cannot show breadth, however many trades there are.
        "too_thin": n_groups < MIN_GROUPS,
    }


MIN_GROUPS = 3


def close_day(closed_at: Optional[str]) -> Optional[str]:
    """UTC calendar day (YYYY-MM-DD) of a close time, or None when it is missing or unparseable."""
    if not closed_at:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(str(closed_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date().isoformat()
