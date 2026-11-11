"""Most-active names and unusual options activity, from free delayed data.

What this is: a ranking of a FIXED liquid universe by dollar volume and relative volume, then a look at the
option chains of the most active names for contracts trading far above their open interest.
What it is not: a full-market screen, an options tape, or evidence of who bought. Volume far above open
interest can be closing, rolling, spreading or hedging. Open interest is a prior-day figure, so intraday volume
against it overstates how unusual a print is. A zero or missing open interest gives NO ratio (never infinity).
Quoted ask x volume is an illustration of scale, not premium actually paid.
Nothing here places an order or feeds the strategy; it is research context and a ranked reading list.
"""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional, Sequence

from .dataquality import check_snapshot
from .market_clock import NY, session_status
from .marketdata import Bar, MarketDataProvider, MarketSnapshot
from .models import Right, utcnow
from .signals import liquidity_tier
from .store import Store

MIN_UNUSUAL_VOLUME = 150
MIN_VOLUME_OI_RATIO = 3.0
MIN_ZERO_OI_VOLUME = 500
RELATIVE_VOLUME_SURGE = 2.0
MIN_BARS = 21
TOP_ACTIVE = 25
CHAINS_BY_DOLLAR_VOLUME = 12
CHAINS_BY_RELATIVE_VOLUME = 6
MAX_UNUSUAL_ROWS = 40
SCAN_BUDGET_S = 90.0

# A fixed, hand-picked universe of liquid, optionable names and funds. Deliberately not "the whole market".
UNIVERSE: tuple[str, ...] = (
    "SPY", "QQQ", "IWM", "DIA", "TLT", "HYG", "GLD", "SLV", "USO", "SMH", "XBI", "EEM", "EFA",
    "XLF", "XLE", "XLK", "XLV", "XLY", "XLP", "XLI", "XLU",
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "NFLX", "COST", "ORCL", "CRM", "ADBE",
    "INTC", "QCOM", "MU", "ARM", "SMCI", "PLTR", "COIN", "MSTR", "SHOP", "UBER", "SNOW", "CRWD", "PANW",
    "JPM", "BAC", "WFC", "GS", "MS", "C", "V", "MA", "XOM", "CVX", "UNH", "LLY", "JNJ", "PFE", "MRK", "ABBV",
    "WMT", "HD", "PG", "KO", "PEP", "DIS", "NKE", "BA", "CAT", "GE",
)


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def completed_bars(bars: Sequence[Bar], now: datetime) -> list[Bar]:
    """Drop today's bar while the session is open: its volume is partial and would look like a collapse."""
    out = [b for b in bars if _finite(b.close) and b.close > 0 and _finite(b.volume) and b.volume >= 0]
    if out and out[-1].day == now.astimezone(NY).date() and session_status(now)[0]:
        out = out[:-1]
    return out


def rank_active(raw: dict[str, Sequence[Bar]], now: datetime, top: int = TOP_ACTIVE) -> list[dict[str, Any]]:
    rows = []
    for sym, bars in raw.items():
        done = completed_bars(bars, now)
        if len(done) < MIN_BARS:
            continue
        last, prev = done[-1], done[-2]
        base = [b.volume for b in done[-MIN_BARS:-1]]
        avg = sum(base) / len(base)
        rel = last.volume / avg if avg > 0 else None
        rows.append({
            "symbol": sym, "day": last.day.isoformat(), "close": round(last.close, 2),
            "change_pct": round((last.close / prev.close - 1) * 100, 2), "volume": int(last.volume),
            "dollar_volume": round(last.close * last.volume),
            "relative_volume": None if rel is None else round(rel, 2),
            "surge": rel is not None and rel >= RELATIVE_VOLUME_SURGE,
        })
    rows.sort(key=lambda r: -r["dollar_volume"])
    for i, r in enumerate(rows, start=1):
        r["rank"] = i
    return rows[:top] if top else rows


def unusual_contracts(snap: MarketSnapshot, now: datetime) -> list[dict[str, Any]]:
    out = []
    for r in snap.rows:
        vol = r.volume or 0
        if vol < MIN_UNUSUAL_VOLUME or r.ask <= 0 or r.bid < 0 or r.bid > r.ask:
            continue
        oi = r.open_interest
        ratio = round(vol / oi, 2) if oi and oi > 0 else None  # no ratio when OI is zero or missing
        if ratio is not None and ratio < MIN_VOLUME_OI_RATIO:
            continue
        if ratio is None and vol < MIN_ZERO_OI_VOLUME:
            continue
        c = r.contract
        dte = (c.expiry - now.date()).days
        spread = (r.ask - r.bid) / r.ask * 100
        tier = liquidity_tier(spread, vol, oi)
        reviewable = tier in ("A", "B") and 7 <= dte <= 730
        out.append({
            "symbol": c.underlying, "contract": c.occ_symbol.strip(), "right": c.right.value, "strike": c.strike,
            "expiry": c.expiry.isoformat(), "dte": dte, "volume": int(vol),
            "open_interest": oi, "oi_state": "MISSING" if oi is None else ("REPORTED_ZERO" if oi == 0 else "REPORTED"),
            "volume_oi_ratio": ratio, "bid": r.bid, "ask": r.ask, "spread_pct": round(spread, 2), "liquidity_tier": tier,
            "moneyness_pct": round((c.strike / snap.underlying - 1) * 100, 2) if snap.underlying > 0 else None,
            "iv": r.iv, "quoted_turnover_usd": round(r.ask * vol * 100),
            "score": round(min(100.0, 10 * math.log1p(vol) + min(35.0, (ratio or 0) * 4)), 1),
            "decision": "REVIEWABLE" if reviewable else "OBSERVE_ONLY",
            "why_observe_only": None if reviewable else ("wide or thin market" if tier == "C" else "expiry outside 7-730 days"),
        })
    return out


def option_totals(snap: MarketSnapshot, unusual_count: int) -> dict[str, Any]:
    cv = sum((r.volume or 0) for r in snap.rows if r.contract.right is Right.CALL)
    pv = sum((r.volume or 0) for r in snap.rows if r.contract.right is Right.PUT)
    return {"symbol": snap.symbol, "call_volume": cv, "put_volume": pv, "total_volume": cv + pv,
            "call_put_ratio": round(cv / pv, 2) if pv > 0 else None, "unusual_count": unusual_count,
            "contracts": len(snap.rows), "expiries": len({r.contract.expiry for r in snap.rows})}


LIMITATIONS = (
    "A fixed universe of about 75 liquid names, not the whole market.",
    "Free Yahoo data is delayed about 15 minutes and unofficial; quote times are not verified.",
    "Only the nearest few expirations of each chain are sampled, so option volume totals are partial.",
    "Open interest updates once a day: intraday volume against it overstates how unusual a print is.",
    "High volume relative to open interest can be closing, rolling, spreading or hedging. Direction is unknown.",
    "Quoted ask x volume is an illustration of scale, not premium actually paid.",
)


class Scanner:
    def __init__(self, provider: MarketDataProvider, store: Store, *, clock: Callable[[], datetime] = utcnow,
                 universe: Sequence[str] = UNIVERSE, budget_s: float = SCAN_BUDGET_S) -> None:
        self.provider, self.store, self.clock = provider, store, clock
        self.universe, self.budget_s = tuple(universe), budget_s
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self.last_error: Optional[str] = None

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Scan in the background. Returns False if one is already running."""
        with self._lock:
            if self.running():
                return False
            self._thread = threading.Thread(target=self._safe_run, name="optplat-scan", daemon=True)
            self._thread.start()
            return True

    def _safe_run(self) -> None:
        try:
            self.run()
            self.last_error = None
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"{type(exc).__name__}: {str(exc)[:120]}"

    def run(self) -> dict[str, Any]:
        t0, now = time.monotonic(), self.clock()
        out: dict[str, Any] = {"as_of": now.isoformat(), "fictional": self.provider.fictional, "source": self.provider.name,
                               "active_names": [], "option_names": [], "unusual": [], "errors": [],
                               "thresholds": {"min_volume": MIN_UNUSUAL_VOLUME, "min_volume_oi_ratio": MIN_VOLUME_OI_RATIO,
                                              "min_volume_when_oi_zero_or_missing": MIN_ZERO_OI_VOLUME,
                                              "relative_volume_surge": RELATIVE_VOLUME_SURGE},
                               "limitations": list(LIMITATIONS)}
        try:
            raw = self.provider.daily_bars(self.universe)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - say so, never fabricate a ranking
            out["errors"].append(f"daily bars unavailable: {type(exc).__name__}: {str(exc)[:100]}")
            self.store.record_scan(now, self.provider.fictional, out)
            return out
        ranked = rank_active(raw, now, top=0)
        out["active_names"] = ranked[:TOP_ACTIVE]
        pick = [r["symbol"] for r in ranked[:CHAINS_BY_DOLLAR_VOLUME]]
        surging = sorted((r for r in ranked if r["surge"] and r["symbol"] not in pick), key=lambda r: -(r["relative_volume"] or 0))
        pick += [r["symbol"] for r in surging[:CHAINS_BY_RELATIVE_VOLUME]]
        scanned = failed = 0
        for sym in pick:
            if time.monotonic() - t0 > self.budget_s:
                out["errors"].append(f"time budget reached after {scanned} chains")
                break
            try:
                checked = check_snapshot(self.provider.snapshot(sym), now)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                out["errors"].append(f"{sym}: chain unavailable ({type(exc).__name__})")
                continue
            if checked.snapshot is None:
                failed += 1
                out["errors"].append(f"{sym}: chain rejected by the data-quality gate")
                continue
            rows = unusual_contracts(checked.snapshot, now)
            out["unusual"].extend(rows)
            out["option_names"].append(option_totals(checked.snapshot, len(rows)))
            scanned += 1
        out["unusual"].sort(key=lambda r: (r["decision"] != "REVIEWABLE", -r["score"], -r["volume"]))
        out["unusual_total"] = len(out["unusual"])
        out["unusual"] = out["unusual"][:MAX_UNUSUAL_ROWS]
        out["option_names"].sort(key=lambda r: -r["total_volume"])
        out["coverage"] = {"universe": len(self.universe), "ranked": len(ranked), "chains_scanned": scanned, "chains_failed": failed,
                           "seconds": round(time.monotonic() - t0, 1)}
        self.store.record_scan(now, self.provider.fictional, out)
        return out

    def latest(self) -> Optional[dict[str, Any]]:
        return self.store.latest_scan(self.provider.fictional)

    def status(self) -> dict[str, Any]:
        latest = self.latest()
        return {"running": self.running(), "last_error": self.last_error, "last_scan_at": latest["as_of"] if latest else None}
