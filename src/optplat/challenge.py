"""The 10x challenge: an aggressive simulated account that may be restarted, with a critic on every trade.

What it is: a separate $10,000 paper account in the ``lane_trades`` ledger, aiming for 10x in 30 days, which is far
beyond what any real strategy should expect. The aim is to push hard, lose cheaply, and learn quickly. When an attempt
ends (target reached, ruined, or the 30 days run out) the result is written to a permanent history and a fresh attempt
starts. Entries are the EMA9/VWAP signal on liquid names, sized as a share of the account's current equity, and every
one is reviewed first by a critic that can refuse it and that writes down its objections and the thesis.

What it is not: an order path, a way to touch the real account, or evidence of anything. It places no orders, uses no
broker and changes no risk limit. Restarting until an attempt works is selection, so the history counts EVERY attempt
and reports the success rate across all of them; one lucky run among many proves nothing. Demo data is labelled
fictional everywhere.

Anything unknown (no quote, no volume, no mark) means no entry, and a position that cannot be marked stays open.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from typing import Any, Optional

from . import shortterm as st_mod
from .liquidity import exit_concession_pct, liquidity_tier
from .marketdata import ChainRow
from .optionlanes import EXTRA_SHORT, EXIT_TEXT, FEE_PER_CONTRACT, MULTIPLIER, OptionLane, Params
from .shortterm import lane_report

START_EQUITY = 10_000.0
GOAL_MULT = 10.0
DAYS = 30
RUIN_FRAC = 0.10            # at or below 10% of the start the attempt is over
RISK_PCT = 0.25             # premium per trade, as a share of current equity
MAX_EXPOSURE_PCT = 0.60     # open premium as a share of equity
MAX_STRESS_CONCESSION_PCT = 12.0
MAX_SIZE_OF_VOLUME_PCT = 10.0
MAX_SIZE_OF_OI_PCT = 15.0
COOL_OFF = timedelta(minutes=60)
HISTORY_CAP = 200

CHALLENGE = Params(
    "challenge-10x", "10x challenge", "short",
    "Aims for 10x in 30 days from $10,000. Same EMA9/VWAP signal, calls and puts, expiry up to a week, 25% of the account per trade, "
    "up to two positions in a name (the second only while the first is winning). A critic can refuse any trade. Restarts when the attempt ends.",
    START_EQUITY * RISK_PCT, 6, 3, 0, 7, 1.0, 12.0, 100, 100, 0.30, 45, 120, 0, True, True, False,
    st_mod.LANE_SYMBOLS + EXTRA_SHORT, max_per_name=2, stack="winners")

EXIT_TEXT_CHALLENGE = {**EXIT_TEXT, "challenge_end": "The attempt ended (target, ruin, deadline or a manual restart), so every open position was closed at the bid."}

LIMITATIONS = (
    "A 10x target in a month needs roughly 11 to 12% compounded every trading day. It is a stress test, not a plan, and pushes towards long shots.",
    "Restarting until an attempt works is selection. Read the success rate across ALL attempts, not the best one.",
    "Fills at the ask and bid are an assumption; the critic stresses the exit but a real order could do worse or not fill.",
    "Free option quotes are delayed and unofficial. Nothing here places an order, and the real account and its risk limits are untouched.",
)


def account_state(trades: list[dict[str, Any]], start: float, marks: dict[int, float]) -> dict[str, Any]:
    """Cash and equity of one attempt from its trades. Open trades are valued at the bid (the last mark, else the
    entry price, which is flagged as unmarked), less the fee to close."""
    realized = open_cost = open_value = 0.0
    unmarked = 0
    for t in trades:
        o = t["open_payload"]
        mult, fee = o.get("multiplier", MULTIPLIER), o.get("fee_per_contract", FEE_PER_CONTRACT)
        cost = t["entry_price"] * t["quantity"] * mult + o.get("fees_open", 0.0)
        if t["closed_at"] is not None:
            cp = t["close_payload"] or {}
            realized += t["exit_price"] * t["quantity"] * mult - cp.get("fees_close", t["quantity"] * fee) - cost
        else:
            bid = marks.get(t["id"])
            if bid is None:
                unmarked += 1
                bid = t["entry_price"]
            open_cost += cost
            open_value += bid * t["quantity"] * mult - t["quantity"] * fee
    cash = start + realized - open_cost
    return {"cash": round(cash, 2), "equity": round(cash + open_value, 2), "realized_pnl": round(realized, 2),
            "open_cost": round(open_cost, 2), "open_value": round(open_value, 2), "unmarked": unmarked}


def required_daily_pct(equity: float, goal: float, days_left: float) -> Optional[float]:
    """Compounded return needed per day to reach the goal, or None when there is no time or no equity left."""
    if equity <= 0 or days_left <= 0:
        return None
    return round((math.pow(goal / equity, 1 / days_left) - 1) * 100, 2)


class ChallengeLane(OptionLane):
    def __init__(self, provider, store, feed, *, clock, calendar=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(provider, store, CHALLENGE, feed, clock=clock, calendar=calendar)
        self._attempt: dict[str, Any] = {}

    # ---------------------------------------------------------------- attempts
    def _load_attempt(self, now: datetime) -> dict[str, Any]:
        raw = self.store.get_state("challenge:attempt", "")
        if raw:
            self._attempt = json.loads(raw)
        else:
            self._attempt = {"n": 1, "started_at": now.isoformat(), "start_equity": START_EQUITY}
            self.store.set_state("challenge:attempt", json.dumps(self._attempt))
        return self._attempt

    def _attempt_trades(self, closed_only: bool = False) -> list[dict[str, Any]]:
        n = self._attempt["n"]
        rows = [t for t in self.store.lane_trades(self.p.lane, self.provider.fictional, 2000) if t["open_payload"].get("attempt") == n]
        return [t for t in rows if t["closed_at"] is not None] if closed_only else rows

    def _marks_by_id(self, trades: list[dict[str, Any]]) -> dict[int, float]:
        out: dict[int, float] = {}
        for t in trades:
            if t["closed_at"] is None:
                raw = self.store.get_state(f"lane_mark:{t['id']}", "")
                if raw:
                    out[t["id"]] = float(json.loads(raw)["bid"])
        return out

    def state_now(self) -> dict[str, Any]:
        trades = self._attempt_trades()
        return account_state(trades, self._attempt["start_equity"], self._marks_by_id(trades))

    def _end_attempt(self, outcome: str, now: datetime, out: dict[str, Any]) -> bool:
        """Close everything at the bid, write the attempt to the history and start the next one. A position with no
        usable quote cannot be closed, so the attempt stays open and the problem is shown."""
        held = self._held()
        marks = self._marks(held, now, out)
        for t in held:
            m = marks.get(t["open_payload"]["contract"])
            if m is None:
                out["errors"].append(f"{t['symbol']}: attempt {self._attempt['n']} should end ({outcome}) but there is no quote to close at; it stays open")
                return False
        for t in held:
            m = marks[t["open_payload"]["contract"]]
            self._close(t, m[0], "challenge_end", now, out, {"underlying": None, "bid": m[0], "ask": m[1],
                                                           "spread_pct": round((m[1] - m[0]) / m[1] * 100, 2) if m[1] > 0 else None})
        trades = self._attempt_trades()
        st = account_state(trades, self._attempt["start_equity"], {})
        closed = [t for t in trades if t["closed_at"] is not None]
        tags: dict[str, int] = {}
        for t in closed:
            for tag in ((t["close_payload"] or {}).get("postmortem") or {}).get("tags", []):
                tags[tag] = tags.get(tag, 0) + 1
        pnls = [((t["exit_price"] - t["entry_price"]) * t["quantity"] * MULTIPLIER) for t in closed]
        entry = {"attempt": self._attempt["n"], "started_at": self._attempt["started_at"], "ended_at": now.isoformat(), "outcome": outcome,
                 "start_equity": self._attempt["start_equity"], "end_equity": st["equity"], "multiple": round(st["equity"] / self._attempt["start_equity"], 2),
                 "trades": len(closed), "wins": sum(1 for x in pnls if x > 0), "best_trade_usd": round(max(pnls), 2) if pnls else None,
                 "worst_trade_usd": round(min(pnls), 2) if pnls else None, "top_causes": sorted(tags.items(), key=lambda kv: -kv[1])[:4]}
        hist = json.loads(self.store.get_state("challenge:history", "[]"))
        hist.append(entry)
        self.store.set_state("challenge:history", json.dumps(hist[-HISTORY_CAP:]))
        self._attempt = {"n": self._attempt["n"] + 1, "started_at": now.isoformat(), "start_equity": START_EQUITY}
        self.store.set_state("challenge:attempt", json.dumps(self._attempt))
        out["note"] = f"attempt {entry['attempt']} ended: {outcome}"
        return True

    def restart(self, now: datetime) -> dict[str, Any]:
        """Owner-requested restart. Counted in the history like any other end, so restarts cannot hide losses."""
        with self._lock:
            out = self._new_out(now)
            self._load_attempt(now)
            ok = self._end_attempt("MANUAL_RESTART", now, out)
            return {**out, "restarted": ok}

    def _lifecycle(self, now: datetime, out: dict[str, Any]) -> None:
        a = self._load_attempt(now)
        st = self.state_now()
        if st["unmarked"] == 0 and st["equity"] >= a["start_equity"] * GOAL_MULT:
            self._end_attempt("TARGET", now, out)
        elif st["unmarked"] == 0 and st["equity"] <= a["start_equity"] * RUIN_FRAC:
            self._end_attempt("RUIN", now, out)
        elif now >= datetime.fromisoformat(a["started_at"]) + timedelta(days=DAYS):
            self._end_attempt("DEADLINE", now, out)

    def step(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            now = self.clock()
            out = self._new_out(now)
            if self._throttled(now, force, out):
                return out
            try:
                self._load_attempt(now)
                self._lifecycle(now, out)   # first: an attempt that is over must not open more trades
                self._step_short(now, out)
            except Exception as exc:  # noqa: BLE001 - a research account must never raise into the engine
                from .diagnostics import describe_exc
                out["errors"].append(describe_exc(exc))
            self._remember(out)
            return out

    # ---------------------------------------------------------------- sizing and the critic
    def _enter(self, sym, right, now, out, signal, held, extra=None, budget_mult=1.0):  # type: ignore[override]
        st = self.state_now()
        budget = min(st["equity"] * RISK_PCT, max(0.0, st["cash"]))
        if budget <= 0:
            out["skips"].append(f"{sym}: no cash left in this attempt")
            return None
        return super()._enter(sym, right, now, out, signal, held, extra={**(extra or {}), "attempt": self._attempt["n"]},
                              budget_mult=budget / self.p.budget_usd)

    def _review(self, sym, right, row: ChainRow, qty, payload, held, now):  # type: ignore[override]
        st = self.state_now()
        eq = st["equity"]
        spread = payload["spread_pct"]
        vol, oi = row.volume or 0, row.open_interest or 0
        tier = liquidity_tier(vol, oi, spread)
        # shrink to what the market could plausibly absorb before judging the rest
        cap = min(int(vol * MAX_SIZE_OF_VOLUME_PCT / 100), int(oi * MAX_SIZE_OF_OI_PCT / 100))
        qty2 = min(qty, cap)
        if qty2 < 1:
            return f"critic: even one contract is too large a share of the market (volume {vol}, open interest {oi})", qty
        stress = exit_concession_pct(qty2, vol, oi, spread)
        cost = row.ask * qty2 * MULTIPLIER
        closed = sorted([t for t in self._attempt_trades(closed_only=True)], key=lambda t: t["closed_at"])
        veto: Optional[str] = None
        if tier == "THIN":
            veto = f"critic: the contract is thin (volume {vol}, open interest {oi}, spread {spread}%): the exit would be a guess"
        elif stress > MAX_STRESS_CONCESSION_PCT:
            veto = f"critic: a less friendly exit would cost {stress}% on top of the spread, too much for the move this needs"
        elif st["open_cost"] + cost > eq * MAX_EXPOSURE_PCT:
            veto = f"critic: {round((st['open_cost'] + cost) / eq * 100)}% of the account would be at risk at once (limit {round(MAX_EXPOSURE_PCT * 100)}%)"
        elif len(closed) >= 3 and all((t["exit_price"] - t["entry_price"]) <= 0 for t in closed[-3:]) and now - datetime.fromisoformat(closed[-1]["closed_at"]) < COOL_OFF:
            veto = "critic: the last three trades all lost; cooling off for an hour instead of chasing"
        else:
            today = now.date().isoformat()
            if any(t["symbol"] == sym and t["close_reason"] == "stop" and t["closed_at"][:10] == today and t["open_payload"]["right"] == right for t in closed):
                veto = f"critic: {sym} already stopped this trade out today; not chasing it"
        if veto:
            return veto, qty
        needed = required_daily_pct(eq, self._attempt["start_equity"] * GOAL_MULT, self.days_left(now))
        objections = []
        if payload["dte"] <= 1:
            objections.append("0 to 1 days to expiry: time decay is fast, so the move has to come within hours")
        if spread > 8:
            objections.append(f"spread {spread}% means it starts about that far under its cost")
        if cost > eq * 0.20:
            objections.append(f"one trade is {round(cost / eq * 100)}% of the account")
        if stress > 5:
            objections.append(f"a less friendly exit would cost about {stress}% more")
        if payload.get("stack_index", 0) > 0:
            objections.append("this adds to a position in the same name, so it is the same idea bet twice")
        if qty2 < qty:
            objections.append(f"size cut from {qty} to {qty2} contracts to stay within {MAX_SIZE_OF_VOLUME_PCT:g}% of volume and {MAX_SIZE_OF_OI_PCT:g}% of open interest")
        sig = payload.get("signal", {})
        payload["critic"] = {
            "verdict": "ACCEPTED_WITH_OBJECTIONS" if objections else "ACCEPTED",
            "objections": objections, "liquidity_tier": tier, "stress_exit_concession_pct": stress,
            "thesis": f"EMA9 {'above' if right == 'C' else 'below'} the session VWAP ({sig.get('ema')} vs {sig.get('vwap')}) suggests the underlying keeps moving {'up' if right == 'C' else 'down'} today.",
            "wrong_if": f"the underlying closes back through the VWAP, or the premium falls {payload['stop_pct']:g}%",
            "needs_pct_per_day_for_goal": needed,
            "account_equity": eq,
        }
        return None, qty2

    # ---------------------------------------------------------------- reporting
    def days_left(self, now: datetime) -> float:
        start = datetime.fromisoformat(self._attempt["started_at"])
        return max(0.0, DAYS - (now - start).total_seconds() / 86400)

    def report(self, now: datetime) -> dict[str, Any]:
        self._load_attempt(now)
        a, st = self._attempt, self.state_now()
        goal, ruin = a["start_equity"] * GOAL_MULT, a["start_equity"] * RUIN_FRAC
        day = DAYS - self.days_left(now)
        straight = a["start_equity"] * math.pow(GOAL_MULT, min(1.0, day / DAYS))
        hist = json.loads(self.store.get_state("challenge:history", "[]"))
        counts = {k: sum(1 for h in hist if h["outcome"] == k) for k in ("TARGET", "RUIN", "DEADLINE", "MANUAL_RESTART")}
        rep = lane_report(self.store, self.p.lane, self.provider.fictional, now, rules=self.rules(), limitations=LIMITATIONS,
                          symbols=self.p.symbols, exit_text=EXIT_TEXT_CHALLENGE)
        raw = self.store.get_state(f"optlane_last_result:{self.p.lane}", "")
        return {**rep, "last_check": json.loads(raw) if raw else None, "label": self.p.label, "fictional": self.provider.fictional,
                "account": {"attempt": a["n"], "started_at": a["started_at"], "day": round(day, 1), "days": DAYS, "start_equity": a["start_equity"],
                            "equity": st["equity"], "cash": st["cash"], "open_premium": st["open_cost"], "realized_pnl": st["realized_pnl"],
                            "multiple": round(st["equity"] / a["start_equity"], 3), "goal_equity": goal, "ruin_equity": ruin,
                            "needed_pct_per_day": required_daily_pct(st["equity"], goal, self.days_left(now)),
                            "straight_line_equity": round(straight, 2), "on_pace": st["equity"] >= straight, "unmarked_open": st["unmarked"]},
                "history": list(reversed(hist[-30:])), "attempts_finished": len(hist), "outcomes": counts,
                "success_rate_pct": round(counts["TARGET"] / len(hist) * 100, 1) if hist else None,
                "honesty": "Counting every attempt, including restarts: "
                           + (f"{counts['TARGET']} of {len(hist)} reached 10x." if hist else "no attempt has finished yet.")
                           + " One success among many tries is what luck alone would produce; it is not evidence of an edge."}

    def rules(self) -> list[str]:
        from .optionlanes import rules_text
        return rules_text(self.p) + [
            f"Account: ${START_EQUITY:,.0f} start, goal {GOAL_MULT:g}x ({GOAL_MULT * START_EQUITY:,.0f}), ruin at {round(RUIN_FRAC * 100)}% of the start, {DAYS} days. Each trade risks up to {round(RISK_PCT * 100)}% of current equity; at most {round(MAX_EXPOSURE_PCT * 100)}% of equity at risk at once.",
            f"The critic refuses: thin contracts, exits that would cost more than {MAX_STRESS_CONCESSION_PCT:g}% extra under stress, a book too exposed, a third trade straight after three losses, and chasing a name stopped out today. It cuts size to {MAX_SIZE_OF_VOLUME_PCT:g}% of volume and {MAX_SIZE_OF_OI_PCT:g}% of open interest, and writes down its objections and what would prove the thesis wrong.",
        ]
