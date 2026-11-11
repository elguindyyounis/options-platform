"""Swing research lane: buy a pullback inside an uptrend on daily bars, hold for days, exit on rules.

What this is: a deterministic rule on completed DAILY bars of the fixed scan universe. A "trade" is a simulated
purchase of shares of the underlying in its own ledger (``lane_trades``), apart from the options account.
What it is not: an options strategy, an order path, or evidence of an edge. It places no orders, touches no broker,
no risk limit and no options position. It is a research experiment until a pre-registered test says otherwise.

The rule and its settings are declared below, before any results exist. Stops and targets are stored with each
trade when it opens, so changing a setting later never moves a trade already open. Anything unknown (bars missing,
too short, the fetch failing, an earnings date unknown for a single stock) means no entry.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional, Sequence

from .agents import rsi, sma
from .events import ETFS, EventCalendar
from .marketdata import Bar, MarketDataProvider
from .models import utcnow
from .scanner import UNIVERSE, completed_bars
from .shortterm import lane_report
from .store import Store

LANE = "swing-pullback"
SYMBOLS: tuple[str, ...] = UNIVERSE

# Research parameters, fixed before any result. Changing them starts a new experiment.
BARS_MONTHS = 6
SMA_FAST = 20
SMA_SLOW = 50
RSI_PERIOD = 14
RSI_DIP = 45                  # the pullback: RSI at or below this on any of the previous DIP_LOOKBACK bars
DIP_LOOKBACK = 3
MAX_DAY_MOVE_PCT = 5.0        # skip a bar that jumped more than this: that is news, not a pullback ending
STOP_VOL_MULT = 2.5           # stop distance = this many daily standard deviations ...
STOP_MIN_PCT, STOP_MAX_PCT = 3.0, 10.0   # ... kept between these
TARGET_R = 1.5                # target distance = this multiple of the stop distance
MAX_HOLD_BARS = 10            # trading days
NOTIONAL_USD = 2000.0         # simulated size per trade
MAX_OPEN = 5
SLIPPAGE_PCT = 0.05           # each way, against the trade
EARNINGS_BUFFER_DAYS = 14     # no entry if earnings fall inside the hold window plus this much
RUN_EVERY = timedelta(minutes=60)
MIN_BARS = SMA_SLOW + DIP_LOOKBACK + 2

RULES = (
    f"Long only, on daily bars of the {len(SYMBOLS)}-name scan universe.",
    f"Enter on a pullback inside an uptrend: the {SMA_FAST}-day average above the {SMA_SLOW}-day average and the close still above the {SMA_SLOW}-day average, "
    f"RSI({RSI_PERIOD}) at or below {RSI_DIP} on one of the last {DIP_LOOKBACK} days, then RSI rising and a higher close. "
    f"Skip a day that moved more than {MAX_DAY_MOVE_PCT:g}%.",
    f"Stop at {STOP_VOL_MULT:g} daily standard deviations below entry (between {STOP_MIN_PCT:g}% and {STOP_MAX_PCT:g}%), "
    f"target {TARGET_R:g} times that distance above. Also exit on a close below the {SMA_SLOW}-day average or after {MAX_HOLD_BARS} trading days.",
    f"Single stocks only when no earnings fall inside the hold plus {EARNINGS_BUFFER_DAYS} days, and the date is known. Funds are exempt.",
    f"Simulated size ${NOTIONAL_USD:,.0f} per trade, at most {MAX_OPEN} open, {SLIPPAGE_PCT}% slippage each way.",
)
LIMITATIONS = (
    "Free daily data is unofficial and delayed. Entries are simulated at the latest completed close, not the next open, so real fills would differ and gaps are not modelled.",
    "These are simulated share trades on the underlying. There is no options leg and no broker, so this does not test the options book.",
    "Earnings dates come from an unofficial feed, and an unknown date for a single stock blocks the entry.",
    "The rule and its settings were fixed before results existed. A few paper trades say nothing about an edge.",
)
EXIT_TEXT = {
    "stop": "The close fell to the stop level set when the trade opened.",
    "target": "The close reached the target set when the trade opened.",
    "trend_break": f"The close fell below the {SMA_SLOW}-day average, so the uptrend the trade relied on was gone.",
    "time": f"{MAX_HOLD_BARS} trading days passed without the stop or the target, so the time stop closed it.",
}


def stop_distance_pct(sigma: float) -> float:
    return min(STOP_MAX_PCT, max(STOP_MIN_PCT, STOP_VOL_MULT * sigma * 100))


def read(bars: Sequence[Bar], now: datetime) -> Optional[dict[str, Any]]:
    """Indicators at the newest completed daily bar, or None when there is not enough trustworthy history."""
    done = completed_bars(bars, now)
    if len(done) < MIN_BARS:
        return None
    closes = [b.close for b in done]
    rsis = [rsi(closes[: len(closes) - k], RSI_PERIOD) for k in range(DIP_LOOKBACK + 1)]  # newest first
    if any(x is None for x in rsis):
        return None
    rets = [closes[i] / closes[i - 1] - 1 for i in range(len(closes) - 20, len(closes))]
    mean = sum(rets) / len(rets)
    sigma = math.sqrt(sum((x - mean) ** 2 for x in rets) / (len(rets) - 1))
    return {"day": done[-1].day, "close": closes[-1], "prev_close": closes[-2], "sma_fast": sma(closes, SMA_FAST),
            "sma_slow": sma(closes, SMA_SLOW), "rsi": rsis[0], "rsi_prev": rsis[1],
            "rsi_dip": min(rsis[1:]), "sigma": sigma, "day_move_pct": (closes[-1] / closes[-2] - 1) * 100, "bars": len(done),
            "days": [b.day for b in done]}


def entry_signal(r: dict[str, Any]) -> bool:
    return (r["sma_fast"] > r["sma_slow"] and r["close"] > r["sma_slow"] and r["rsi_dip"] <= RSI_DIP and r["rsi"] > r["rsi_prev"]
            and r["close"] > r["prev_close"] and abs(r["day_move_pct"]) <= MAX_DAY_MOVE_PCT)


def exit_reason(opened: dict[str, Any], r: dict[str, Any]) -> Optional[str]:
    p = opened["open_payload"]
    held = sum(1 for d in r["days"] if d.isoformat() > p["bar_day"])
    if r["close"] <= p["stop"]:
        return "stop"
    if r["close"] >= p["target"]:
        return "target"
    if r["close"] < r["sma_slow"]:
        return "trend_break"
    if held >= p.get("max_hold_bars", MAX_HOLD_BARS):
        return "time"
    return None


class SwingLane:
    def __init__(self, provider: MarketDataProvider, store: Store, *, clock: Callable[[], datetime] = utcnow,
                 calendar: Optional[EventCalendar] = None, symbols: Sequence[str] = SYMBOLS) -> None:
        self.provider, self.store, self.clock, self.calendar, self.symbols = provider, store, clock, calendar, tuple(symbols)

    def _earnings_ok(self, sym: str, today: date) -> bool:
        if sym.upper() in ETFS:
            return True
        if self.calendar is None:
            return False  # no calendar consulted: a single stock is not allowed
        ev = self.calendar.earnings(sym, today, today + timedelta(days=int(MAX_HOLD_BARS * 1.5) + EARNINGS_BUFFER_DAYS))
        return ev is not None and not ev  # unknown (None) and "earnings coming" both block

    def step(self, *, force: bool = False) -> dict[str, Any]:
        """One pass. Throttled to once an hour unless forced. Exits first, then at most MAX_OPEN entries."""
        now = self.clock()
        fict = self.provider.fictional
        out: dict[str, Any] = {"at": now.isoformat(), "opened": [], "closed": [], "errors": [], "skipped": 0}
        last = self.store.get_state("swing_last_run", "")
        if not force and last and now - datetime.fromisoformat(last) < RUN_EVERY:
            out["note"] = "throttled"
            return out
        self.store.set_state("swing_last_run", now.isoformat())
        try:
            raw = self.provider.daily_bars(self.symbols, months=BARS_MONTHS)  # type: ignore[call-arg]
        except Exception as exc:  # noqa: BLE001 - no data means no entry, and the reason is shown
            out["errors"].append(f"daily bars unavailable: {type(exc).__name__}: {str(exc)[:100]}")
            return out
        open_by = {t["symbol"]: t for t in self.store.lane_trades(LANE, fict, 2000) if t["closed_at"] is None}
        reads = {sym: read(raw.get(sym, []), now) for sym in self.symbols}
        for sym, held in list(open_by.items()):
            r = reads.get(sym)
            why = exit_reason(held, r) if r else None
            if why:
                px = round(r["close"] * (1 - SLIPPAGE_PCT / 100), 4)
                if self.store.lane_close(held["id"], now, px, why, {"day": r["day"].isoformat(), "close": round(r["close"], 4), "sma_slow": round(r["sma_slow"], 4)}):
                    out["closed"].append({"symbol": sym, "reason": why})
                    open_by.pop(sym)
        for sym in self.symbols:
            r = reads.get(sym)
            if r is None or sym in open_by:
                continue
            key = f"swing_last_bar:{sym}"
            if self.store.get_state(key, "") == r["day"].isoformat():
                continue  # this bar was already judged
            self.store.set_state(key, r["day"].isoformat())
            if not entry_signal(r):
                continue
            if len(open_by) >= MAX_OPEN or not self._earnings_ok(sym, now.date()):
                out["skipped"] += 1
                continue
            px = round(r["close"] * (1 + SLIPPAGE_PCT / 100), 4)
            qty = int(NOTIONAL_USD // px)
            if qty < 1:
                continue
            k = stop_distance_pct(r["sigma"])
            payload = {"bar_day": r["day"].isoformat(), "close": round(r["close"], 4), "sma_fast": round(r["sma_fast"], 4),
                       "sma_slow": round(r["sma_slow"], 4), "rsi": r["rsi"], "rsi_prev": r["rsi_prev"], "rsi_dip": r["rsi_dip"],
                       "sigma_pct": round(r["sigma"] * 100, 3), "stop_pct": round(k, 2),
                       "stop": round(px * (1 - k / 100), 4), "target": round(px * (1 + TARGET_R * k / 100), 4),
                       "max_hold_bars": MAX_HOLD_BARS}
            tid = self.store.lane_open(LANE, sym, now, px, qty, fict, payload)
            open_by[sym] = {"id": tid, "symbol": sym}
            out["opened"].append({"symbol": sym})
        return out


def build_report(store: Store, fictional: bool, now: datetime) -> dict[str, Any]:
    return lane_report(store, LANE, fictional, now, rules=RULES, limitations=LIMITATIONS, symbols=SYMBOLS, exit_text=EXIT_TEXT)
