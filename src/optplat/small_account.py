"""The $1,000 account: the aggressive short-term rule under the limits a real $1,000 cash account would have.

Why (owner, 2026-11-28, capital plan tier 1): the platform will start live with about $1,000. The other lanes spend
$1,000 to $10,000 a trade, so none of them says whether the short-term edge survives at the size that will actually be
traded. This lane asks exactly that, on paper: the same EMA9/VWAP signal and exits as "Short-term options, aggressive",
with these limits on top:

* one balance, starting at $1,000, that is NEVER restarted (a restart would hide a loss; see the 10x challenge's note);
* each trade spends at most 10% of current equity, and at most 25% of equity is in open premium at once;
* only contracts that cost $1.00 or less (at most $100 each), so one contract fits the budget;
* only settled cash: options settle the next business day, so money from a trade closed today is not spent today;
* a daily brake: no new entry after the day's closed trades lost 10% of the equity the day started with.

Written down before its first trade (2026-11-28): the lane is worth taking live only if, after fees, its closed trades
make money and it does at least as well per dollar as the frozen baseline over the same dates. Until it has 30 or more
closed trades on 30 or more days, its result is noise.

It places no orders, uses no broker and changes no risk limit. Anything unknown means no entry.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from . import shortterm as st_mod
from .challenge import account_state
from .market_clock import NY
from .marketdata import ChainRow
from .optionlanes import EXTRA_SHORT, EXIT_TEXT, FEE_PER_CONTRACT, MULTIPLIER, OptionLane, Params, rules_text
from .shortterm import lane_report

LANE = "small-account-1k"
START_EQUITY = 1_000.0
RISK_PCT = 0.10              # premium per trade, as a share of current equity
MAX_OPEN_PCT = 0.25          # open premium, as a share of current equity
MAX_ASK = 1.00               # dollars per share: at most $100 a contract
DAILY_LOSS_PCT = 0.10        # of the equity the day started with

SMALL = Params(
    LANE, "$1,000 account", "short",
    "The aggressive short-term rule (EMA9 against the session VWAP, calls and puts, expiry up to four days, slightly out of the money) "
    "with the limits of a real $1,000 cash account: 10% of equity per trade, 25% open at most, contracts of $1.00 or less, settled cash only, "
    "and no new entries after a 10% losing day. One balance, never restarted.",
    START_EQUITY * RISK_PCT, 2, 2, 0, 4, 0.5, 20.0, 25, 5, 0.10, 40, 100, 0, True, True, False,
    st_mod.LANE_SYMBOLS + EXTRA_SHORT)

LIMITATIONS = (
    "Fills at the ask and the bid are assumed. Cheap contracts have the widest spreads, so a real fill could be worse or not happen.",
    "Contracts of $1.00 or less are mostly far out of the money or near expiry: they need a fast move and lose value quickly.",
    "Commissions are modelled at $0.65 a contract each way; on a $50 contract that is about 2.6% round trip.",
    "Paper results on a few dozen trades prove nothing. Nothing here places an order or touches the real account.",
)


def _et_day(iso: str):
    return datetime.fromisoformat(iso).astimezone(NY).date()


def day_figures(trades: list[dict[str, Any]], start: float, now: datetime) -> dict[str, float]:
    """Proceeds that have not settled yet and the day's realized result, from the lane's trades.

    Options settle the next business day: the sale proceeds of a trade closed today are cash, but not yet settled cash.
    The day's result counts closed trades only; the short-term rule never holds overnight, so the day starts flat."""
    today = now.astimezone(NY).date()
    unsettled = day_pnl = before = 0.0
    for t in trades:
        if t["closed_at"] is None:
            continue
        o, cp = t["open_payload"], t["close_payload"] or {}
        mult, fee = o.get("multiplier", MULTIPLIER), o.get("fee_per_contract", FEE_PER_CONTRACT)
        proceeds = t["exit_price"] * t["quantity"] * mult - cp.get("fees_close", t["quantity"] * fee)
        pnl = proceeds - (t["entry_price"] * t["quantity"] * mult + o.get("fees_open", 0.0))
        if _et_day(t["closed_at"]) == today:
            unsettled += proceeds
            day_pnl += pnl
        else:
            before += pnl
    return {"unsettled": round(unsettled, 2), "day_pnl": round(day_pnl, 2), "day_start_equity": round(start + before, 2)}


def drawdown(trades: list[dict[str, Any]], start: float) -> dict[str, Optional[float]]:
    """Peak equity and the deepest drop from a peak, from closed trades in the order they closed."""
    eq = peak = start
    worst = 0.0
    for t in sorted((t for t in trades if t["closed_at"] is not None), key=lambda t: t["closed_at"]):
        eq = account_state([t], eq, {})["cash"]
        peak = max(peak, eq)
        worst = max(worst, (peak - eq) / peak * 100 if peak > 0 else 0.0)
    return {"peak_equity": round(peak, 2), "max_drawdown_pct": round(worst, 1)}


class SmallAccountLane(OptionLane):
    max_ask = MAX_ASK

    def __init__(self, provider, store, feed, *, clock, calendar=None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(provider, store, SMALL, feed, clock=clock, calendar=calendar)

    def _trades(self) -> list[dict[str, Any]]:
        return self.store.lane_trades(LANE, self.provider.fictional, 2000)

    def _marks_by_id(self, trades: list[dict[str, Any]]) -> dict[int, float]:
        out: dict[int, float] = {}
        for t in trades:
            if t["closed_at"] is None:
                raw = self.store.get_state(f"lane_mark:{t['id']}", "")
                if raw:
                    out[t["id"]] = float(json.loads(raw)["bid"])
        return out

    def state_now(self, now: datetime) -> dict[str, Any]:
        trades = self._trades()
        st = account_state(trades, START_EQUITY, self._marks_by_id(trades))
        day = day_figures(trades, START_EQUITY, now)
        return {**st, **day, "settled_cash": round(max(0.0, st["cash"] - day["unsettled"]), 2)}

    def _enter(self, sym, right, now, out, signal, held, extra=None, budget_mult=1.0):  # type: ignore[override]
        st = self.state_now(now)
        if st["day_pnl"] <= -DAILY_LOSS_PCT * st["day_start_equity"]:
            out["skips"].append(f"{sym}: today's closed trades lost {abs(st['day_pnl']):,.2f}, the 10% daily brake; no new entries until tomorrow")
            return None
        room = MAX_OPEN_PCT * st["equity"] - st["open_cost"]
        budget = min(RISK_PCT * st["equity"], st["settled_cash"], room)
        if budget < 10:   # not even a $0.10 contract
            out["skips"].append(f"{sym}: only ${max(budget, 0):,.2f} may be spent now (settled cash, 10% per trade, 25% open)")
            return None
        return super()._enter(sym, right, now, out, signal, held, extra=extra, budget_mult=budget / self.p.budget_usd)

    def _review(self, sym, right, row: ChainRow, qty, payload, held, now):  # type: ignore[override]
        if row.ask > MAX_ASK:   # pick_contract already filters; this is the fail-closed backstop
            return f"the contract costs ${row.ask:.2f}, over the ${MAX_ASK:.2f} limit", qty
        payload["account_equity"] = self.state_now(now)["equity"]
        return None, qty

    def report(self, now: datetime) -> dict[str, Any]:
        trades = self._trades()
        st = self.state_now(now)
        rep = lane_report(self.store, LANE, self.provider.fictional, now, rules=self.rules(), limitations=LIMITATIONS,
                          symbols=self.p.symbols, exit_text=EXIT_TEXT)
        raw = self.store.get_state(f"optlane_last_result:{LANE}", "")
        return {**rep, "last_check": json.loads(raw) if raw else None, "label": self.p.label, "fictional": self.provider.fictional,
                "account": {"start_equity": START_EQUITY, "equity": st["equity"], "cash": st["cash"], "settled_cash": st["settled_cash"],
                            "open_premium": st["open_cost"], "realized_pnl": st["realized_pnl"], "day_pnl": st["day_pnl"],
                            "return_pct": round((st["equity"] / START_EQUITY - 1) * 100, 2), "unmarked_open": st["unmarked"],
                            **drawdown(trades, START_EQUITY)}}

    def rules(self) -> list[str]:
        return rules_text(self.p) + [
            f"Account: ${START_EQUITY:,.0f}, never restarted. Each trade spends up to {round(RISK_PCT * 100)}% of current equity, from settled cash only; "
            f"at most {round(MAX_OPEN_PCT * 100)}% of equity is open at once.",
            f"Only contracts at ${MAX_ASK:.2f} or less (${MAX_ASK * MULTIPLIER:,.0f} a contract). No new entry after the day's closed trades lose "
            f"{round(DAILY_LOSS_PCT * 100)}% of the equity it started with.",
        ]
