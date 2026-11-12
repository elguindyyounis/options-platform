"""Automatic post-mortems for closed simulated option trades.

Every closed trade in an options research lane gets a short, deterministic write-up: what happened, which of a
fixed set of causes fit, and what to test next. The point is to turn each loss (and each win) into a labelled
data point, so the digest can show which kinds of trades keep failing instead of leaving that to memory.

What this is not: a diagnosis. The causes are rules of thumb applied to a handful of numbers, and "try next"
lines are hypotheses to test in a lane, never changes the platform applies by itself. A few trades prove nothing.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

MIN_TRADES_FOR_PATTERN = 5

# tag -> (what it means in a sentence, what to test next)
CAUSES: dict[str, tuple[str, str]] = {
    "TARGET_HIT": ("The premium reached its profit target.", "Check whether a higher target would have kept more of the move before changing it."),
    "STOPPED_QUICKLY": ("The stop was hit almost at once, so the entry was early or the move was noise.",
                        "Test waiting for a second confirming bar before entering."),
    "STOPPED": ("The premium fell to its stop.", "Compare against a wider stop on the same entries before tightening or widening."),
    "WRONG_DIRECTION": ("The underlying moved against the position.", "Test adding a trend or market-breadth filter to the entry."),
    "RIGHT_DIRECTION_LOST_MONEY": ("The underlying moved the right way but the option still lost: decay, a falling IV or the spread took more than the move paid.",
                                   "Test a longer expiry or a strike closer to the money."),
    "TIME_DECAY": ("A short-dated option lost value as time passed while the underlying went nowhere.",
                   "Test longer expiries; the lane with the longer window is the comparison."),
    "SPREAD_ATE_GAIN": ("The move was smaller than the cost of crossing the spread and fees, in and out.",
                        "Test a tighter spread limit, or skip contracts with a thin open interest."),
    "WIDE_SPREAD_ENTRY": ("The entry spread was wide, so the position started well below its cost.", "Test a tighter maximum spread."),
    "THIN_MARKET": ("The contract had little open interest, so the simulated fills are probably better than a real one would have been.",
                    "Treat this result as optimistic, and test a higher open interest floor."),
    "EARNINGS_GAMBLE": ("An earnings date was close or unknown when this was opened, so a gap and an IV drop were possible.",
                        "Compare trades with and without a nearby earnings date before keeping this experiment."),
    "VWAP_LOST": ("The underlying closed back through the session VWAP, the exit rule for the short-term lane.", "Compare against holding to the stop or target only."),
    "FLAT_BY_CLOSE": ("It was closed before the end of the session because the lane never holds overnight.", "Check whether the trade was still working at the close."),
    "TREND_BREAK": ("The underlying closed through its 50-day average, the swing trend rule.", "Check how often this exit saved a loss versus ended a winner early."),
    "TIME_STOP": ("The holding limit passed without the stop or the target.", "Check whether a shorter or longer limit changes the result."),
    "EXPIRY_NEAR": ("It was closed close to expiry to avoid assignment and pin risk.", "Check whether a longer expiry would have let the idea play out."),
    "STACKED": ("This was added on top of an existing position in the same name, so one idea was bet on twice or more.",
                "Compare stacked trades with first entries: if stacks lose more, stacking is not paying."),
    "OVERSIZED_FOR_LIQUIDITY": ("The size was a large share of the contract's volume or open interest, so a real order would probably have moved the price or not filled.",
                                "Cap size at a share of volume, and see whether the result survives."),
    "BIG_WIN": ("A large gain from a long-shot structure.", "Check how many similar trades lost; one big win is not an edge."),
    "UNMARKED": ("No usable quote at the close, so it was closed at the intrinsic value.", "Check the data feed for this contract."),
}


def _hours(open_at: str, close_at: datetime) -> Optional[float]:
    try:
        return (close_at - datetime.fromisoformat(open_at)).total_seconds() / 3600
    except ValueError:
        return None


def post_mortem(trade: dict[str, Any], exit_price: float, reason: str, closed_at: datetime, close_info: dict[str, Any]) -> dict[str, Any]:
    """``trade`` is the open lane row (with ``open_payload``). Returns tags, a headline and short lessons."""
    p = trade["open_payload"]
    entry, qty = trade["entry_price"], trade["quantity"]
    mult = p.get("multiplier", 100)
    gross_pct = (exit_price / entry - 1) * 100 if entry > 0 else 0.0
    fees = p.get("fees_open", 0.0) + close_info.get("fees_close", 0.0)
    net = (exit_price - entry) * qty * mult - fees
    cost = entry * qty * mult
    net_pct = net / cost * 100 if cost > 0 else 0.0
    call = p.get("right") == "C"
    und0, und1 = p.get("underlying_price"), close_info.get("underlying")
    move = (und1 / und0 - 1) * 100 if und0 and und1 else None
    right_way = None if move is None else (move > 0) == call and move != 0
    held_h = _hours(trade["opened_at"], closed_at)
    spread_in = p.get("spread_pct")
    friction_pct = ((spread_in or 0) + (close_info.get("spread_pct") or 0)) + (fees / cost * 100 if cost > 0 else 0)

    tags: list[str] = []
    won = net > 0
    if reason == "target":
        tags.append("TARGET_HIT")
    if reason == "stop":
        tags.append("STOPPED_QUICKLY" if held_h is not None and held_h < (1.5 if p.get("dte", 99) <= 10 and p.get("kind") == "short" else 36) else "STOPPED")
    if not won:
        if right_way is False:
            tags.append("WRONG_DIRECTION")
        elif right_way:
            tags.append("RIGHT_DIRECTION_LOST_MONEY")
        if reason in ("time", "flat_by_close", "vwap_lost") and p.get("dte", 99) <= 10 and right_way is not False:
            tags.append("TIME_DECAY")
    if abs(gross_pct) * 1.0 < friction_pct and "TARGET_HIT" not in tags:
        tags.append("SPREAD_ATE_GAIN")
    if (spread_in or 0) >= 10:
        tags.append("WIDE_SPREAD_ENTRY")
    if p.get("stack_index", 0) > 0:
        tags.append("STACKED")
    if (p.get("size_vs_volume_pct") or 0) > 10 or (p.get("size_vs_oi_pct") or 0) > 5:
        tags.append("OVERSIZED_FOR_LIQUIDITY")
    if (p.get("open_interest") or 0) < 50:
        tags.append("THIN_MARKET")
    if p.get("earnings_state") in ("SOON", "UNKNOWN"):
        tags.append("EARNINGS_GAMBLE")
    tags.append({"vwap_lost": "VWAP_LOST", "flat_by_close": "FLAT_BY_CLOSE", "carried_over": "FLAT_BY_CLOSE", "trend_break": "TREND_BREAK", "time": "TIME_STOP",
                 "expiry_near": "EXPIRY_NEAR", "expired_unmarked": "UNMARKED"}.get(reason, ""))
    if won and net_pct >= 100:
        tags.append("BIG_WIN")
    tags = [t for t in dict.fromkeys(tags) if t]

    name = p.get("contract", trade["symbol"])
    moved = "" if move is None else f" The underlying moved {move:+.2f}%."
    headline = (f"{'Won' if won else 'Lost'} {abs(net_pct):.0f}% on {name}: {gross_pct:+.0f}% on the premium before fees, closed on "
                f"{reason.replace('_', ' ')}.{moved}")
    shown = [t for t in tags if t in CAUSES][:4]
    return {"tags": tags, "headline": headline, "net_pct": round(net_pct, 1), "gross_pct": round(gross_pct, 1),
            "underlying_move_pct": None if move is None else round(move, 2), "held_hours": None if held_h is None else round(held_h, 1),
            "lessons": [CAUSES[t][0] for t in shown], "try_next": [CAUSES[t][1] for t in shown]}


def digest(closed: list[dict[str, Any]]) -> dict[str, Any]:
    """Which causes keep showing up, across closed trades that carry a post-mortem. Patterns need MIN_TRADES_FOR_PATTERN."""
    by_tag: dict[str, list[float]] = {}
    for t in closed:
        pm = (t.get("close_payload") or {}).get("postmortem")
        if not pm:
            continue
        for tag in pm["tags"]:
            by_tag.setdefault(tag, []).append(pm["net_pct"])
    rows = []
    for tag, rets in by_tag.items():
        if tag not in CAUSES:
            continue
        wins = sum(1 for x in rets if x > 0)
        rows.append({"tag": tag, "count": len(rets), "win_rate_pct": round(wins / len(rets) * 100, 1),
                     "avg_net_pct": round(sum(rets) / len(rets), 1), "means": CAUSES[tag][0], "try_next": CAUSES[tag][1],
                     "pattern": len(rets) >= MIN_TRADES_FOR_PATTERN})
    rows.sort(key=lambda r: (not r["pattern"], r["avg_net_pct"]))
    return {"tags": rows, "trades_reviewed": sum(1 for t in closed if (t.get("close_payload") or {}).get("postmortem")),
            "note": f"A cause counts as a pattern only after {MIN_TRADES_FOR_PATTERN} trades. Until then it is an anecdote."}
