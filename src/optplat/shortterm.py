"""Short-term research lane: an intraday EMA9 / VWAP paper experiment on the underlying.

What this is: a deterministic rule evaluated on completed 5-minute bars. A "trade" is a simulated purchase of
shares of the underlying, recorded in its own ledger (``lane_trades``), apart from the options account.
What it is not: an options strategy, an order path, or evidence of an edge. It places no orders, touches no
broker and no risk limit, and its results prove nothing until a pre-registered experiment says otherwise.

Honest limits, repeated in the dashboard: free data is delayed about 15 minutes, so a real fill at the price used
here was never available; fills assume a fixed slippage; the rule parameters below are research settings chosen
before looking at results, and the owner should review them. Anything unknown (no bars, stale bars, too few bars,
a failed fetch) means no entry.
"""
from __future__ import annotations

import math
from datetime import datetime, time, timedelta
from typing import Any, Callable, Optional, Sequence

from .market_clock import NY
from .marketdata import IntradayBar, MarketDataProvider
from .models import utcnow
from .store import Store

LANE = "shortterm-ema9-vwap"
LANE_SYMBOLS: tuple[str, ...] = ("SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA")

# Research parameters. Declared here, before any results exist. Changing them starts a new experiment.
BAR_MINUTES = 5
EMA_PERIOD = 9
MIN_BARS = 12                 # at least an hour of session before the first signal
ENTRY_FROM = time(10, 0)      # New York time
ENTRY_UNTIL = time(15, 0)
FLAT_BY = time(15, 45)        # never carried overnight
STOP_PCT = 0.5
TARGET_PCT = 1.0
SLIPPAGE_PCT = 0.05           # each way, against the trade
NOTIONAL_USD = 1000.0         # simulated size per trade
MAX_OPEN = 3
MAX_BAR_AGE_S = 1800          # a bar older than this (after its own end) is stale: no new entry

RULES = (
    f"Long only, on {BAR_MINUTES}-minute bars of: {', '.join(LANE_SYMBOLS)}.",
    f"Enter when the {EMA_PERIOD}-bar EMA crosses above the session VWAP and the bar closes above VWAP, "
    f"between {ENTRY_FROM:%H:%M} and {ENTRY_UNTIL:%H:%M} New York time, after at least {MIN_BARS} bars.",
    f"Exit when a bar closes below VWAP, at a {STOP_PCT}% stop, at a {TARGET_PCT}% target, or flat by {FLAT_BY:%H:%M}.",
    f"Simulated size ${NOTIONAL_USD:,.0f} per trade, at most {MAX_OPEN} open, {SLIPPAGE_PCT}% slippage each way.",
)
LIMITATIONS = (
    "Free data is delayed about 15 minutes, so the prices used here were not available to act on at the time.",
    "These are simulated share trades on the underlying. There is no options leg and no broker.",
    "The risk policy keeps real options entries at 7 or more days to expiry, so nothing here can become an options day trade without an owner decision.",
    "The rule and its settings were fixed before results existed. A handful of paper trades says nothing about an edge.",
)


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def ema(values: Sequence[float], n: int) -> list[float]:
    k = 2.0 / (n + 1)
    out: list[float] = []
    for v in values:
        out.append(v if not out else out[-1] + k * (v - out[-1]))
    return out


def completed(bars: Sequence[IntradayBar], now: datetime) -> list[IntradayBar]:
    """Bars that have fully closed, valid, in time order, for the New York session of the newest bar."""
    ok = [b for b in bars if _finite(b.close) and b.close > 0 and _finite(b.high) and _finite(b.low) and _finite(b.volume)
          and b.volume >= 0 and b.ts + timedelta(minutes=BAR_MINUTES) <= now]
    ok.sort(key=lambda b: b.ts)
    if not ok:
        return []
    day = ok[-1].ts.astimezone(NY).date()
    return [b for b in ok if b.ts.astimezone(NY).date() == day]


def read(bars: Sequence[IntradayBar], now: datetime) -> Optional[dict[str, Any]]:
    """Indicator values at the newest completed bar, or None when there is not enough trustworthy data."""
    done = completed(bars, now)
    if len(done) < MIN_BARS:
        return None
    pv = vol = 0.0
    vwaps: list[Optional[float]] = []
    for b in done:
        pv += (b.high + b.low + b.close) / 3 * b.volume
        vol += b.volume
        vwaps.append(pv / vol if vol > 0 else None)
    if vwaps[-1] is None or vwaps[-2] is None:
        return None
    e = ema([b.close for b in done], EMA_PERIOD)
    last = done[-1]
    return {"bar_ts": last.ts, "bar_end": last.ts + timedelta(minutes=BAR_MINUTES), "close": last.close, "ema": e[-1],
            "prev_ema": e[-2], "vwap": vwaps[-1], "prev_vwap": vwaps[-2], "bars": len(done)}


def entry_signal(r: dict[str, Any]) -> bool:
    return r["prev_ema"] <= r["prev_vwap"] and r["ema"] > r["vwap"] and r["close"] > r["vwap"]


def in_entry_window(now: datetime) -> bool:
    t = now.astimezone(NY).time()
    return ENTRY_FROM <= t <= ENTRY_UNTIL


def exit_reason(entry_price: float, r: Optional[dict[str, Any]], now: datetime, opened_at: datetime) -> Optional[str]:
    if opened_at.astimezone(NY).date() != now.astimezone(NY).date():
        return "carried_over"
    if now.astimezone(NY).time() >= FLAT_BY:
        return "flat_by_close"
    if r is None:
        return None
    if r["close"] <= entry_price * (1 - STOP_PCT / 100):
        return "stop"
    if r["close"] >= entry_price * (1 + TARGET_PCT / 100):
        return "target"
    if r["close"] < r["vwap"]:
        return "below_vwap"
    return None


EXIT_TEXT = {
    "stop": "The bar closed at the stop level.", "target": "The bar closed at the target.",
    "below_vwap": "The bar closed below the session VWAP, the exit rule for this lane.",
    "flat_by_close": "Closed before the end of the session: the lane never holds overnight.",
    "carried_over": "Found open from an earlier day and closed at the first current price.",
}


class ShortTermLane:
    def __init__(self, provider: MarketDataProvider, store: Store, *, clock: Callable[[], datetime] = utcnow,
                 symbols: Sequence[str] = LANE_SYMBOLS) -> None:
        self.provider, self.store, self.clock, self.symbols = provider, store, clock, tuple(symbols)

    def step(self) -> dict[str, Any]:
        """Evaluate every symbol once. Exits are always evaluated; entries only on a new, fresh, completed bar."""
        now = self.clock()
        fict = self.provider.fictional
        out: dict[str, Any] = {"at": now.isoformat(), "opened": [], "closed": [], "errors": []}
        open_by_symbol = {t["symbol"]: t for t in self.store.lane_trades(LANE, fict, 2000) if t["closed_at"] is None}
        for sym in self.symbols:
            try:
                r = read(self.provider.intraday_bars(sym), now)
            except Exception as exc:  # noqa: BLE001 - unknown data means no entry, and the reason is shown
                out["errors"].append(f"{sym}: {type(exc).__name__}: {str(exc)[:80]}")
                r = None
            fresh = r is not None and (now - r["bar_end"]).total_seconds() <= MAX_BAR_AGE_S
            held = open_by_symbol.get(sym)
            if held is not None:
                why = exit_reason(held["entry_price"], r if fresh else None, now, datetime.fromisoformat(held["opened_at"]))
                if why and r is not None and (fresh or why in ("flat_by_close", "carried_over")):
                    px = round(r["close"] * (1 - SLIPPAGE_PCT / 100), 4)
                    if self.store.lane_close(held["id"], now, px, why, {"vwap": round(r["vwap"], 4), "ema": round(r["ema"], 4), "bar": r["bar_ts"].isoformat()}):
                        out["closed"].append({"symbol": sym, "reason": why})
                        open_by_symbol.pop(sym, None)
                continue
            if not fresh or r is None:
                continue
            key = f"shortterm_last_bar:{sym}"
            if self.store.get_state(key, "") == r["bar_ts"].isoformat():
                continue  # this bar was already judged
            self.store.set_state(key, r["bar_ts"].isoformat())
            if not (in_entry_window(now) and entry_signal(r)) or len(open_by_symbol) >= MAX_OPEN:
                continue
            px = round(r["close"] * (1 + SLIPPAGE_PCT / 100), 4)
            qty = int(NOTIONAL_USD // px)
            if qty < 1:
                continue
            tid = self.store.lane_open(LANE, sym, now, px, qty, fict, {
                "bar": r["bar_ts"].isoformat(), "close": round(r["close"], 4), "ema": round(r["ema"], 4), "vwap": round(r["vwap"], 4),
                "prev_ema": round(r["prev_ema"], 4), "prev_vwap": round(r["prev_vwap"], 4), "bars": r["bars"]})
            open_by_symbol[sym] = {"id": tid}
            out["opened"].append({"symbol": sym})
        return out


def build_report(store: Store, fictional: bool, now: datetime) -> dict[str, Any]:
    rows = store.lane_trades(LANE, fictional, 500)
    trades = []
    for t in rows:
        closed = t["closed_at"] is not None
        pnl = round((t["exit_price"] - t["entry_price"]) * t["quantity"], 2) if closed else None
        cost = t["entry_price"] * t["quantity"]
        trades.append({
            "id": t["id"], "symbol": t["symbol"], "opened_at": t["opened_at"], "closed_at": t["closed_at"], "quantity": t["quantity"],
            "entry_price": t["entry_price"], "exit_price": t["exit_price"], "pnl": pnl,
            "pnl_pct": round(pnl / cost * 100, 2) if pnl is not None and cost > 0 else None,
            "status": "CLOSED" if closed else "OPEN", "close_reason": t["close_reason"],
            "close_text": EXIT_TEXT.get(t["close_reason"] or "", None), "why_entered": t["open_payload"],
        })
    done = [t for t in trades if t["status"] == "CLOSED"]
    wins = [t for t in done if (t["pnl"] or 0) > 0]
    return {
        "lane": LANE, "fictional": fictional, "as_of": now.isoformat(), "rules": list(RULES), "limitations": list(LIMITATIONS),
        "symbols": list(LANE_SYMBOLS),
        "summary": {"total": len(trades), "open": len(trades) - len(done), "closed": len(done), "wins": len(wins),
                    "win_rate_pct": round(len(wins) / len(done) * 100, 1) if done else None,
                    "realized_pnl": round(sum(t["pnl"] for t in done), 2),
                    "min_trades_for_evidence": 30},
        "trades": trades,
    }
