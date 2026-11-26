"""Market regime: should a NEW put or call be opened into this market at all?

Owner decision 2026-11-24: the overall market state must steer call versus put, not each name's own trend alone. On a
day SPY bounced hard after a deep drop, many puts were open because every name's own 20/50-day trend still pointed down.

The reading uses several signals so no single indicator decides (RSI alone is slow and says nothing about a thrust day):
SPY's distance below its 20-day high, how far it sits from its 20-day average, RSI(14), the day's and the 3-day return, and,
when known, the share of scanned names that rose and the VIX. Counts of signals decide, never one number.

Rules (they only TIGHTEN entries; nothing here opens or sizes a trade, and exits are untouched):
  * a new PUT is blocked when the market is oversold twice over, or oversold and bouncing, or bouncing hard twice;
  * a new CALL is blocked in the mirror image (overbought, selling off).
Thresholds are engineering choices made before any result, not tuned numbers and not an edge. Whether the guard helps is
hypothesis R1 in docs/EVOLUTION_PLAN.md; blocked entries are journalled with the reading so R1 can count them.
Unknown data never blocks (a missing SPY series cannot be read as a signal) and is reported as unknown.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional, Sequence

from .agents import rsi, sma
from .models import utcnow

MIN_BARS = 21
OVERSOLD_RSI, OVERBOUGHT_RSI = 30.0, 70.0
DRAWDOWN_PCT = 8.0          # below the 20-day high
STRETCH_BELOW_SMA20_PCT = 3.0
STRETCH_ABOVE_SMA20_PCT = 5.0
BOUNCE_DAY_PCT, BOUNCE_3D_PCT = 1.5, 3.0
BREADTH_THRUST_PCT, BREADTH_WASHOUT_PCT = 80.0, 15.0   # share of scanned names that rose on the day
VIX_PANIC = 30.0
TTL = timedelta(minutes=5)


def guard_enabled() -> bool:
    return os.environ.get("OPTPLAT_REGIME_GUARD", "1") != "0"


@dataclass(frozen=True)
class Regime:
    label: str                         # oversold_bounce | oversold | bounce | overbought | selloff | uptrend | downtrend | mixed
    block_puts: bool
    block_calls: bool
    oversold: tuple[str, ...] = ()
    bounce: tuple[str, ...] = ()
    overbought: tuple[str, ...] = ()
    selloff: tuple[str, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "block_puts": self.block_puts, "block_calls": self.block_calls, "oversold": list(self.oversold),
                "bounce": list(self.bounce), "overbought": list(self.overbought), "selloff": list(self.selloff), "facts": self.facts}

    def check(self, right: str) -> tuple[bool, str]:
        """(allowed, plain reason). ``right`` is "C"/"P" or "CALL"/"PUT"."""
        r = right.upper()[:1]
        if r == "P" and self.block_puts:
            return False, "New puts blocked: market is " + self.label.replace("_", " ") + " (" + "; ".join(self.oversold + self.bounce) + ")"
        if r == "C" and self.block_calls:
            return False, "New calls blocked: market is " + self.label.replace("_", " ") + " (" + "; ".join(self.overbought + self.selloff) + ")"
        return True, ""


def read_regime(closes: Sequence[float], *, breadth_up_pct: Optional[float] = None, vix: Optional[float] = None) -> Optional[Regime]:
    """The regime from SPY's daily closes (latest last, today's partial bar allowed). None when there are too few bars."""
    c = [float(x) for x in closes if x and x > 0]
    if len(c) < MIN_BARS:
        return None
    last, prev = c[-1], c[-2]
    day = (last / prev - 1) * 100
    d3 = (last / c[-4] - 1) * 100 if len(c) >= 4 else 0.0
    high20 = max(c[-20:])
    dd = (1 - last / high20) * 100
    s20 = sma(c, 20)
    ext = (last / s20 - 1) * 100
    r = rsi(c)
    if vix is not None and not 5.0 <= vix <= 100.0:
        vix = None  # not a plausible VIX (a provider that invents a bar for any symbol): unknown, never a signal
    over: list[str] = []
    bounce: list[str] = []
    ob: list[str] = []
    sell: list[str] = []
    if r is not None and r < OVERSOLD_RSI:
        over.append(f"RSI {r}")
    if dd >= DRAWDOWN_PCT:
        over.append(f"{dd:.1f}% below the 20-day high")
    if ext <= -STRETCH_BELOW_SMA20_PCT:
        over.append(f"{-ext:.1f}% below the 20-day average")
    if vix is not None and vix >= VIX_PANIC:
        over.append(f"VIX {vix:.0f}")
    if breadth_up_pct is not None and breadth_up_pct <= BREADTH_WASHOUT_PCT:
        over.append(f"only {breadth_up_pct:.0f}% of names up")
    if day >= BOUNCE_DAY_PCT:
        bounce.append(f"SPY {day:+.1f}% today")
    if d3 >= BOUNCE_3D_PCT:
        bounce.append(f"{d3:+.1f}% in 3 days")
    if breadth_up_pct is not None and breadth_up_pct >= BREADTH_THRUST_PCT:
        bounce.append(f"{breadth_up_pct:.0f}% of names up")
    if r is not None and r > OVERBOUGHT_RSI:
        ob.append(f"RSI {r}")
    if ext >= STRETCH_ABOVE_SMA20_PCT:
        ob.append(f"{ext:.1f}% above the 20-day average")
    if day <= -BOUNCE_DAY_PCT:
        sell.append(f"SPY {day:+.1f}% today")
    if d3 <= -BOUNCE_3D_PCT:
        sell.append(f"{d3:+.1f}% in 3 days")
    block_puts = len(over) >= 2 or (len(over) >= 1 and len(bounce) >= 1) or len(bounce) >= 2
    block_calls = len(ob) >= 2 or (len(ob) >= 1 and len(sell) >= 1) or len(sell) >= 2
    s50 = sma(c, 50) if len(c) >= 50 else None
    if block_puts:
        label = "oversold_bounce" if over and bounce else ("oversold" if over else "bounce")
    elif block_calls:
        label = "overbought" if ob else "selloff"
    elif s50 is not None and last > s20 > s50:
        label = "uptrend"
    elif s50 is not None and last < s20 < s50:
        label = "downtrend"
    else:
        label = "mixed"
    facts = {"spy": round(last, 2), "day_pct": round(day, 2), "d3_pct": round(d3, 2), "drawdown_20d_pct": round(dd, 2), "ext_sma20_pct": round(ext, 2),
             "rsi14": r, "vix": vix, "breadth_up_pct": breadth_up_pct}
    return Regime(label, block_puts, block_calls, tuple(over), tuple(bounce), tuple(ob), tuple(sell), facts)


class RegimeSource:
    """Reads SPY (and the VIX when the provider has it) at most once per TTL. ``load`` returns SPY's daily closes."""

    def __init__(self, load: Callable[[], Sequence[float]], clock: Callable[[], datetime] = utcnow, *,
                 load_vix: Optional[Callable[[], Optional[float]]] = None,
                 breadth: Optional[Callable[[], Optional[float]]] = None) -> None:
        self._load, self._clock, self._vix, self._breadth = load, clock, load_vix, breadth
        self._lock = threading.Lock()
        self._hit: Optional[tuple[datetime, Optional[Regime]]] = None

    def read(self) -> Optional[Regime]:
        now = self._clock()
        with self._lock:
            if self._hit and 0 <= (now - self._hit[0]).total_seconds() < TTL.total_seconds():
                return self._hit[1]
        reg: Optional[Regime] = None
        try:
            def opt(fn: Optional[Callable[[], Optional[float]]]) -> Optional[float]:
                try:
                    return fn() if fn else None
                except Exception:  # noqa: BLE001 - optional input
                    return None
            reg = read_regime(self._load(), breadth_up_pct=opt(self._breadth), vix=opt(self._vix))
        except Exception:  # noqa: BLE001 - unknown never blocks
            reg = None
        with self._lock:
            self._hit = (now, reg)
        return reg

    def allows(self, right: str) -> tuple[bool, str, Optional[Regime]]:
        """(allowed, reason, regime). Never blocks when the guard is switched off or the regime is unknown."""
        if not guard_enabled():
            return True, "", None
        reg = self.read()
        if reg is None:
            return True, "", None
        ok, why = reg.check(right)
        return ok, why, reg


def spy_source(provider: Any, clock: Callable[[], datetime] = utcnow) -> RegimeSource:
    """A RegimeSource over a provider's daily bars (SPY; the VIX only if the provider can supply ^VIX)."""
    def load() -> list[float]:
        return [b.close for b in provider.daily_bars(["SPY"], months=4)["SPY"]]

    def vix() -> Optional[float]:
        bars = provider.daily_bars(["^VIX"], months=1).get("^VIX")
        return float(bars[-1].close) if bars else None

    return RegimeSource(load, clock, load_vix=vix)


def describe(source: RegimeSource, *, data_source: str, fictional: bool) -> dict[str, Any]:
    """What the Desk shows: is the guard on, what does it read right now, and what does that block.

    Display only. ``state`` is "off", "unknown" or "known"; unknown and off block nothing (see ``RegimeSource.allows``), and the
    reading says so instead of looking like an all-clear. The thresholds are engineering choices, not an edge.
    """
    base: dict[str, Any] = {"guard_on": guard_enabled(), "data_source": data_source, "fictional": bool(fictional), "authorizes_orders": False,
                            "note": "Engineering thresholds chosen before any result, not an edge. This line authorizes nothing; it only explains why a new put or call may be held back."}
    if not base["guard_on"]:
        return {**base, "state": "off", "puts_allowed": True, "calls_allowed": True, "label": None, "reasons": [], "facts": {}}
    reg = source.read()
    if reg is None:
        return {**base, "state": "unknown", "puts_allowed": True, "calls_allowed": True, "label": None, "reasons": [], "facts": {}}
    return {**base, "state": "known", "puts_allowed": not reg.block_puts, "calls_allowed": not reg.block_calls, "label": reg.label,
            "reasons": [reg.check("P")[1]] * reg.block_puts + [reg.check("C")[1]] * reg.block_calls, "facts": reg.facts}
