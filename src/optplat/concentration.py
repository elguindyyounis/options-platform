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


def win_rate_interval(wins: int, n: int) -> dict:
    """Wilson 95% interval for a win rate. A bare "60% win rate" on 5 trades is compatible with almost anything;
    this shows how wide the doubt is. Display-only. It assumes trades are independent, which they are not (same
    day, same underlying), so the real interval is wider. None when there are no closed trades."""
    if n <= 0 or wins < 0 or wins > n:
        return {"n": max(n, 0), "low_pct": None, "high_pct": None, "too_thin": True, "excludes_half": None}
    z = 1.96
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    low, high = max(0.0, centre - half) * 100, min(1.0, centre + half) * 100
    return {"n": n, "low_pct": round(low, 1), "high_pct": round(high, 1), "too_thin": n < MIN_TRADES,
            # True only when the whole interval sits on one side of a coin flip.
            "excludes_half": bool(low > 50.0 or high < 50.0)}


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


def closed_trade_drawdown(pairs: Sequence[tuple]) -> dict:
    """Largest fall in cumulative realized P&L when closed trades are taken in close-time order.

    `pairs` are (closed_at, pnl). This is NOT account drawdown: it ignores unrealized losses on open
    positions and anything between closes, so the real worst dip was at least this deep. The curve
    starts at 0, so a losing start counts. Trades closed in the same instant are taken losses first
    (the pessimistic order). Trades with no parseable close time or no P&L cannot be placed in the
    sequence; they are counted in `unordered`, never guessed.
    """
    from datetime import datetime, timezone

    def _when(v: Optional[str]) -> Optional[datetime]:
        if not v:
            return None
        try:
            dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None
        return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)

    with_pnl = [(c, float(p)) for c, p in pairs if p is not None]
    placed = [(w, p) for w, p in ((_when(c), p) for c, p in with_pnl) if w is not None]
    placed.sort(key=lambda x: (x[0], x[1]))  # equal times: losses first
    cum = peak = worst = 0.0
    for _, p in placed:
        cum += p
        peak = max(peak, cum)
        worst = max(worst, peak - cum)
    return {
        "basis": "closed_trades_only",
        "is_account_drawdown": False,
        "is_lower_bound": True,
        "closed": len(with_pnl),
        "ordered": len(placed),
        "unordered": len(with_pnl) - len(placed),
        "max_drawdown_usd": round(worst, 2) if placed else None,
        "too_thin": len(placed) < MIN_TRADES,
    }


def lane_selection(lanes: Sequence[dict]) -> dict:
    """Selection-bias check across lanes (display-only). `lanes` are per-source summaries that carry `label`,
    `closed`, `realized_pnl` and `concentration`. With many lanes, the best one looks good more often than a
    single lane would by luck alone, so a headline "best lane" needs its sample size and its one-trade check
    beside it. Lanes with no closed trades are counted but never ranked. Nothing here says any lane has an edge."""
    seen = len(lanes)
    judged = [l for l in lanes if (l.get("closed") or 0) > 0 and l.get("realized_pnl") is not None]
    positive = [l for l in judged if l["realized_pnl"] > 0]
    solid = [l for l in positive if (l["concentration"] or {}).get("one_trade_story") is False
             and not (l["concentration"] or {}).get("too_thin", True)]
    out = {"lanes_seen": seen, "lanes_with_closed_trades": len(judged), "lanes_positive": len(positive),
           "lanes_positive_and_not_thin_or_one_trade": len(solid),
           "lanes_too_thin": sum(1 for l in judged if (l["concentration"] or {}).get("too_thin", True)),
           "best_lane": None, "best_lane_pnl": None, "best_lane_closed": None, "best_lane_too_thin": None,
           "best_lane_one_trade_story": None}
    if judged:
        best = max(judged, key=lambda l: (l["realized_pnl"], l.get("label") or ""))
        c = best["concentration"] or {}
        out.update(best_lane=best.get("label"), best_lane_pnl=best["realized_pnl"], best_lane_closed=best["closed"],
                   best_lane_too_thin=bool(c.get("too_thin", True)), best_lane_one_trade_story=c.get("one_trade_story"))
    # Choosing the best of several lanes after the fact is selection: with more than one lane judged, a leader
    # that is thin or rests on one trade is not evidence of anything.
    out["selection_warning"] = bool(len(judged) > 1 and out["best_lane"] is not None
                                    and (out["best_lane_too_thin"] or out["best_lane_one_trade_story"]))
    out["note"] = ("Picking the best of several lanes after the fact flatters it. A leader that is thin (under "
                   f"{MIN_TRADES} closed trades) or rests on one trade is luck until shown otherwise.")
    return out
