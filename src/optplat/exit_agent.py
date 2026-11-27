"""The exit agent: decides whether to keep holding, trim or exit an open long option, from evidence, not from one fixed percentage.

Owner request (2026-11-27): the trim point should be automatic and the exit decision should be a judgement about whether
to keep holding, not a hard number. It is deterministic and explains itself; language models never place orders.

What it reads (all already in the snapshot and quote, nothing new is fetched): whether the underlying's trend still
agrees with the option's direction (5/20-day averages, 3-day move, stretched RSI), how wide the exit spread is, the gain
or loss, and whether half was already sold.

What it cannot override (kept on purpose, so the agent can only exit EARLIER than the old rules, never later in a loss):
the expiry window, the stop loss, and the stop-to-entry on the rest of a trimmed position. It also falls back to the old
fixed rules whenever it lacks evidence (fewer than 21 daily closes, no snapshot): unknown means the old, stricter rules.
What it adds: holding past the old take-profit while the trend holds, trimming half of a 2+ contract winner when the
evidence weakens or the gain is large, and cutting a loser (or a gain) early when the trend has turned against the trade.
Nothing here is validated; X6 in docs/EVOLUTION_PLAN.md compares it with the fixed rules on recorded paths.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from .agents import rsi, sma
from .exits import EXIT, HOLD, TRIM, ExitDecision, ExitPolicy, evaluate_exit
from .models import Position, Quote, Right

MIN_CLOSES = 21
TRIM_MIN_GAIN_PCT = 15.0      # no trim below this gain: too small to bank
TRIM_BIG_GAIN_PCT = 40.0      # at or above this gain a 2+ contract winner is trimmed whatever the evidence says
HOLD_PAST_TARGET = 0.65       # hold evidence needed to keep a position past the old take-profit
WEAK = 0.45                   # below this the trend no longer supports the trade
BROKEN = 0.30                 # below this the trade's reason is gone: leave


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def hold_evidence(position: Position, quote: Quote, closes: Sequence[float]) -> Optional[tuple[float, dict]]:
    """0 to 1: how well the underlying still supports this option (0.5 = neutral). None when the closes are too few."""
    if len(closes) < MIN_CLOSES or any(c <= 0 for c in closes[-MIN_CLOSES:]):
        return None
    d = 1 if position.contract.right is Right.CALL else -1
    last, s5, s20 = closes[-1], sma(closes, 5), sma(closes, 20)
    trend, slope, mom3 = d * (last / s20 - 1), d * (s5 / s20 - 1), d * (last / closes[-4] - 1)
    score = 0.5 + 0.25 * _clamp(slope / 0.02, -1, 1) + 0.15 * _clamp(mom3 / 0.03, -1, 1) + 0.10 * _clamp(trend / 0.03, -1, 1)
    r = rsi(closes)
    notes = {"trend_vs_sma20_pct": round(trend * 100, 2), "sma5_vs_sma20_pct": round(slope * 100, 2), "move_3d_pct": round(mom3 * 100, 2), "rsi14": r}
    if r is not None and ((d > 0 and r > 75) or (d < 0 and r < 25)):
        score -= 0.15
        notes["stretched"] = True
    spread = quote.spread_pct_of_ask()
    notes["exit_spread_pct"] = round(spread, 1)
    if spread > 15:
        score -= 0.10  # a wide spread is costly to leave later
    return round(_clamp(score, 0.0, 1.0), 3), notes


def decide(position: Position, quote: Optional[Quote], closes: Optional[Sequence[float]], *, entry_time: Optional[datetime],
           now: datetime, policy: ExitPolicy, trimmed: bool = False) -> ExitDecision:
    """The agent's call. ``policy`` supplies the old fixed levels (the floors and the fallback)."""
    base = evaluate_exit(position, quote, entry_time=entry_time, now=now, policy=policy)
    if base.action not in (HOLD, EXIT) or base.trigger in ("expiry_window", "stop_loss", "max_days_held") or quote is None:
        return base                                   # unobservable, or a floor the agent may not override
    pnl = base.pnl_pct if base.pnl_pct is not None else 0.0
    if trimmed and pnl <= 0:
        return ExitDecision(EXIT, f"Stop to entry on the rest after a trim, at {pnl}%", pnl, "stop_to_entry")
    ev = hold_evidence(position, quote, closes or ())
    if ev is None:
        return base                                   # no evidence: the old fixed rules, never looser
    h, notes = ev
    tag = f"hold evidence {h:.2f} ({notes['trend_vs_sma20_pct']:+.1f}% vs 20d, 3d {notes['move_3d_pct']:+.1f}%)"
    if h < BROKEN:
        return ExitDecision(EXIT, f"Trend has turned against the trade: {tag}; leaving at {pnl}%", pnl, "agent_thesis_broken")
    can_trim = position.quantity >= 2 and not trimmed
    if pnl >= TRIM_MIN_GAIN_PCT:
        if can_trim and (pnl >= TRIM_BIG_GAIN_PCT or h < WEAK):
            return ExitDecision(TRIM, f"Bank half at {pnl}%: {tag}", pnl, "agent_trim")
        if pnl >= policy.take_profit_pct and h < HOLD_PAST_TARGET:
            return ExitDecision(EXIT, f"Past the target at {pnl}% without strong support: {tag}", pnl, "agent_take_profit")
        return ExitDecision(HOLD, f"Keep holding at {pnl}%: {tag}", pnl)
    return ExitDecision(HOLD, f"Keep holding at {pnl}%: {tag}", pnl)
