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
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional, Sequence

from .dataquality import check_snapshot
from .diagnostics import describe_exc
from .market_clock import HOLIDAYS, NY, OPEN, session_status
from .marketdata import Bar, MarketDataProvider, MarketSnapshot
from .models import Right, utcnow
from .signals import liquidity_tier
from .store import Store
from .universe import SECTOR_OF, SECTORS, UNIVERSE  # noqa: F401  (UNIVERSE is re-exported for the lanes and tests)

MIN_UNUSUAL_VOLUME = 150
MIN_VOLUME_OI_RATIO = 3.0
MIN_ZERO_OI_VOLUME = 500
LOW_OI = 10                      # open interest below this is "fresh": a few hundred contracts is a new position, not churn
MIN_LOW_OI_VOLUME = 100          # a lower volume bar applies when OI is 1..LOW_OI-1, because the ratio is already extreme
RELATIVE_VOLUME_SURGE = 2.0
MIN_BARS = 21
TOP_ACTIVE = 25
CHAINS_BY_DOLLAR_VOLUME = 30
CHAINS_BY_RELATIVE_VOLUME = 20
CHAINS_FOR_FOLLOW_UP = 25        # names with an unusual contract on an earlier day are always re-read first
MAX_UNUSUAL_ROWS = 60
MAX_FOLLOW_UPS = 40
SCAN_BUDGET_S = 240.0
OI_CONFIRM_FRACTION = 0.5        # OI rose (or fell) by at least this share of the earlier day's volume
MAX_DAYS_APART = 4               # a weekend is fine; a longer gap mixes several sessions into one OI change
SCAN_MIN_DTE, SCAN_MAX_DTE, SCAN_EXPIRIES = 3, 120, 4   # weeklies included: unusual flow often sits there
RATIO_MIN_OI = 20                # the alerter caps the score below this OI: a tiny denominator makes volume/OI look huge
SIDE_AT_QUOTE = 0.2              # a last trade within this share of the spread of a quote counts as "at" it


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


def session_day(now: datetime) -> date:
    """The trading day the volume and open interest in a chain belong to: weekends, listed holidays and the time
    before the open belong to the previous session. Used to key the day-by-day memory."""
    local = now.astimezone(NY)
    d = local.date()
    if local.weekday() < 5 and local.time() < OPEN:
        d -= timedelta(days=1)
    while d.weekday() >= 5 or d in HOLIDAYS.get(d.year, frozenset()):
        d -= timedelta(days=1)
    return d


def trade_side(last: Optional[float], bid: float, ask: float) -> tuple[str, str]:
    """Guess which side the last trade hit from where it printed against the quote. Returns (print, likely_side).

    This is an inference from one price. The last trade need not be the bulk of the volume, and the quote may have
    moved since it printed, so a price far outside the quote (probably stale) gives UNKNOWN rather than a guess."""
    if last is None or last <= 0 or ask <= 0 or bid < 0 or bid > ask:
        return "UNKNOWN", "UNCLEAR"
    spread = ask - bid
    slack = max(spread, 0.05 * ask)
    if last >= ask:
        if last - ask > slack:
            return "UNKNOWN", "UNCLEAR"
        return ("AT_ASK" if last == ask else "ABOVE_ASK"), "BUY"
    if last <= bid:
        if bid - last > slack:
            return "UNKNOWN", "UNCLEAR"
        return ("AT_BID" if last == bid else "BELOW_BID"), "SELL"
    pos = (last - bid) / spread  # spread > 0 here, because bid < last < ask
    if pos >= 1 - SIDE_AT_QUOTE:
        return "AT_ASK", "BUY"
    if pos <= SIDE_AT_QUOTE:
        return "AT_BID", "SELL"
    return "MID", "UNCLEAR"


def unusual_contracts(snap: MarketSnapshot, now: datetime) -> list[dict[str, Any]]:
    out = []
    for r in snap.rows:
        vol = r.volume or 0
        if r.ask <= 0 or r.bid < 0 or r.bid > r.ask:
            continue
        oi = r.open_interest
        low_oi = oi is not None and 0 < oi < LOW_OI
        if vol < (MIN_LOW_OI_VOLUME if low_oi else MIN_UNUSUAL_VOLUME):
            continue
        ratio = round(vol / oi, 2) if oi and oi > 0 else None  # no ratio when OI is zero or missing
        if ratio is not None and ratio < MIN_VOLUME_OI_RATIO:
            continue
        if ratio is None and vol < MIN_ZERO_OI_VOLUME:
            continue
        c = r.contract
        dte = (c.expiry - now.date()).days
        spread = (r.ask - r.bid) / r.ask * 100
        # liquidity grades the OPEN interest too, so a brand-new low-OI contract is tier C by design: the engine's
        # own entry filter would refuse it, and the dashboard says why instead of hiding it.
        tier = liquidity_tier(spread, vol, oi)
        reviewable = tier in ("A", "B") and 7 <= dte <= 730
        printed, side = trade_side(r.last, r.bid, r.ask)
        out.append({
            "symbol": c.underlying, "sector": SECTOR_OF.get(c.underlying), "contract": c.occ_symbol.strip(), "right": c.right.value,
            "strike": c.strike, "expiry": c.expiry.isoformat(), "dte": dte, "volume": int(vol),
            "open_interest": oi, "oi_state": "MISSING" if oi is None else ("REPORTED_ZERO" if oi == 0 else "REPORTED"),
            "low_oi": low_oi or oi == 0, "volume_oi_ratio": ratio,
            # display only: says whether volume/OI rests on a denominator big enough to mean something
            "ratio_basis": "OI_MISSING" if oi is None else ("OI_TINY" if oi < RATIO_MIN_OI else "OI_OK"), "bid": r.bid, "ask": r.ask, "last": r.last,
            "spread_pct": round(spread, 2), "liquidity_tier": tier,
            "print": printed, "likely_side": side,
            "moneyness_pct": round((c.strike / snap.underlying - 1) * 100, 2) if snap.underlying > 0 else None,
            "iv": r.iv, "quoted_turnover_usd": round(r.ask * vol * 100), "underlying_price": snap.underlying,
            "score": round(min(100.0, 10 * math.log1p(vol) + min(35.0, (ratio or 0) * 4) + (15 if low_oi else 0)), 1),
            "decision": "REVIEWABLE" if reviewable else "OBSERVE_ONLY",
            "why_observe_only": None if reviewable else ("wide or thin market" if tier == "C" else "expiry outside 7-730 days"),
        })
    return out


# ------------------------------------------------------------ does it stick the next day, and was it an open or a close
def compare_with_prior(prior: dict[str, Any], oi_now: Optional[int], day: date) -> dict[str, Any]:
    """Compare an earlier day's unusual sighting with today's reported open interest.

    Open interest is reported once a day for the CLOSE of the day before. So today's figure minus the figure that
    was reported on the sighting day is the effect of the sighting day's trading. If it rose by a good share of that
    day's volume, the trades mostly opened positions; if it fell by that much, they mostly closed them. This is
    inference: spreads, rolls and same-day round trips blur it, and free data may update open interest late."""
    prior_day = date.fromisoformat(prior["day"])
    out: dict[str, Any] = {"prior_day": prior["day"], "prior_volume": prior["volume"], "prior_oi": prior.get("open_interest"),
                           "prior_side": prior.get("likely_side", "UNCLEAR"), "oi_now": oi_now, "oi_change": None,
                           "oi_verdict": "UNKNOWN", "position_read": "UNCLEAR", "lean": "UNCLEAR"}
    if (day - prior_day).days > MAX_DAYS_APART:
        out["oi_verdict"] = "TOO_FAR_APART"
        return out
    if oi_now is None or prior.get("open_interest") is None:
        return out
    change = oi_now - prior["open_interest"]
    out["oi_change"] = change
    vol = max(prior["volume"], 1)
    if change >= OI_CONFIRM_FRACTION * vol:
        out["oi_verdict"] = "OI_ROSE"
    elif change <= -OI_CONFIRM_FRACTION * vol:
        out["oi_verdict"] = "OI_FELL"
    else:
        out["oi_verdict"] = "OI_FLAT_OR_MIXED"
    side, verdict = out["prior_side"], out["oi_verdict"]
    if side in ("BUY", "SELL") and verdict in ("OI_ROSE", "OI_FELL"):
        out["position_read"] = f"{side}_TO_{'OPEN' if verdict == 'OI_ROSE' else 'CLOSE'}"
    call = prior.get("right") == Right.CALL.value
    if out["position_read"] in ("BUY_TO_OPEN", "SELL_TO_OPEN"):
        bullish = (out["position_read"] == "BUY_TO_OPEN") == call
        out["lean"] = "BULLISH" if bullish else "BEARISH"
    return out


def follow_ups(snap: MarketSnapshot, prior: dict[str, dict[str, Any]], now: datetime, day: date) -> list[dict[str, Any]]:
    """For every contract of this name that was unusual on an earlier day, read today's open interest and volume."""
    mine = {k: v for k, v in prior.items() if v.get("symbol") == snap.symbol}
    if not mine:
        return []
    by_contract = {r.contract.occ_symbol.strip(): r for r in snap.rows}
    out = []
    for key, p in mine.items():
        r = by_contract.get(key)
        if r is None:
            continue  # expired, or outside the sampled expirations: nothing to read
        cmp = compare_with_prior(p, r.open_interest, day)
        c = r.contract
        dte = (c.expiry - now.date()).days
        spread = (r.ask - r.bid) / r.ask * 100 if r.ask > 0 and r.bid <= r.ask else None
        printed, side = trade_side(r.last, r.bid, r.ask) if r.ask > 0 else ("UNKNOWN", "UNCLEAR")
        out.append({**cmp, "symbol": snap.symbol, "sector": SECTOR_OF.get(snap.symbol), "contract": key, "right": c.right.value,
                    "strike": c.strike, "expiry": c.expiry.isoformat(), "dte": dte, "bid": r.bid, "ask": r.ask, "last": r.last,
                    "spread_pct": None if spread is None else round(spread, 2), "volume_today": int(r.volume or 0),
                    "underlying_price": snap.underlying, "iv": r.iv, "prior_ratio": p.get("volume_oi_ratio"),
                    "prior_tier": p.get("liquidity_tier"), "prior_low_oi": bool(p.get("low_oi")),
                    "prior_score": p.get("score"), "print_today": printed, "side_today": side})
    return out


def annotate_with_history(rows: list[dict[str, Any]], prior: dict[str, dict[str, Any]], store: Store, day: date, fictional: bool) -> None:
    """Mark today's unusual rows that were also unusual on an earlier day, with how it has changed since."""
    for r in rows:
        p = prior.get(r["contract"])
        r["sightings"] = 1
        if p is None:
            continue
        r["sightings"] = store.unusual_streak(day.isoformat(), fictional, r["contract"]) + 1
        r["history"] = compare_with_prior(p, r["open_interest"], day)


# ------------------------------------------------------------ market heat map and sentiment
def heat_map(ranked: list[dict[str, Any]]) -> dict[str, Any]:
    """Sector tiles and name tiles from the ranked daily bars. Moves are the latest completed day against the one before."""
    names, by_sector = [], {}
    for r in ranked:
        sec = SECTOR_OF.get(r["symbol"], "Other")
        names.append({"symbol": r["symbol"], "sector": sec, "change_pct": r["change_pct"], "relative_volume": r["relative_volume"],
                      "dollar_volume": r["dollar_volume"]})
        by_sector.setdefault(sec, []).append(r)
    sectors = []
    for sec, rows in by_sector.items():
        moves = [x["change_pct"] for x in rows]
        rels = [x["relative_volume"] for x in rows if x["relative_volume"] is not None]
        lead = sorted(rows, key=lambda x: -abs(x["change_pct"]))[:3]
        sectors.append({"sector": sec, "names": len(rows), "avg_change_pct": round(sum(moves) / len(moves), 2),
                        "advancers": sum(1 for m in moves if m > 0), "decliners": sum(1 for m in moves if m < 0),
                        "dollar_volume": sum(x["dollar_volume"] for x in rows),
                        "avg_relative_volume": round(sum(rels) / len(rels), 2) if rels else None,
                        "surging": sum(1 for x in rows if x["surge"]),
                        "leaders": [{"symbol": x["symbol"], "change_pct": x["change_pct"]} for x in lead]})
    sectors.sort(key=lambda x: -x["avg_change_pct"])
    return {"sectors": sectors, "names": names}


def sentiment(ranked: list[dict[str, Any]], option_names: list[dict[str, Any]], unusual: list[dict[str, Any]]) -> dict[str, Any]:
    """Plain-words reading of the stock tape and the option flow. Every label is an inference from partial free data."""
    up = sum(1 for r in ranked if r["change_pct"] > 0)
    down = sum(1 for r in ranked if r["change_pct"] < 0)
    n = len(ranked)
    breadth = up / n * 100 if n else None
    spy = next((r for r in ranked if r["symbol"] == "SPY"), None)
    if breadth is None:
        tone = "UNKNOWN"
    elif breadth >= 65:
        tone = "BROAD_STRENGTH"
    elif breadth <= 35:
        tone = "BROAD_WEAKNESS"
    else:
        tone = "MIXED"
    cv = sum(x["call_volume"] for x in option_names)
    pv = sum(x["put_volume"] for x in option_names)
    bull = bear = unclear = 0.0
    for u in unusual:
        usd = u["quoted_turnover_usd"]
        call = u["right"] == Right.CALL.value
        if u["likely_side"] == "BUY":
            bull, bear = (bull + usd, bear) if call else (bull, bear + usd)
        elif u["likely_side"] == "SELL":
            bull, bear = (bull, bear + usd) if call else (bull + usd, bear)
        else:
            unclear += usd
    known = bull + bear
    if known <= 0 or known < 0.3 * (known + unclear):
        flow = "UNCLEAR"
    elif bull / known >= 0.6:
        flow = "BULLISH_LEAN"
    elif bear / known >= 0.6:
        flow = "BEARISH_LEAN"
    else:
        flow = "BALANCED"
    return {"tone": tone, "advancers": up, "decliners": down, "names": n, "breadth_pct": None if breadth is None else round(breadth, 1),
            "spy_change_pct": None if spy is None else spy["change_pct"], "surging_names": sum(1 for r in ranked if r["surge"]),
            "call_volume": cv, "put_volume": pv, "call_put_ratio": round(cv / pv, 2) if pv > 0 else None,
            "flow_lean": flow, "bullish_flow_usd": round(bull), "bearish_flow_usd": round(bear), "unclear_flow_usd": round(unclear),
            "basis": "Flow lean counts only unusual contracts whose last trade printed at the ask (buy) or the bid (sell). "
                     "It is an inference from one price per contract, not a tape."}


def option_totals(snap: MarketSnapshot, unusual_count: int) -> dict[str, Any]:
    cv = sum((r.volume or 0) for r in snap.rows if r.contract.right is Right.CALL)
    pv = sum((r.volume or 0) for r in snap.rows if r.contract.right is Right.PUT)
    return {"symbol": snap.symbol, "call_volume": cv, "put_volume": pv, "total_volume": cv + pv,
            "call_put_ratio": round(cv / pv, 2) if pv > 0 else None, "unusual_count": unusual_count,
            "contracts": len(snap.rows), "expiries": len({r.contract.expiry for r in snap.rows})}


LIMITATIONS = (
    f"A fixed universe of about {len(UNIVERSE)} liquid names from mega-caps down to mid-caps, not the whole market.",
    "Free Yahoo data is delayed about 15 minutes and unofficial; quote times are not verified.",
    "Only the nearest few expirations of each chain are sampled, so option volume totals are partial.",
    "Open interest updates once a day: intraday volume against it overstates how unusual a print is.",
    "Buy or sell is guessed from where the last trade printed against the quote. It is one price per contract, not a tape.",
    "Opened or closed is guessed from the next day's change in open interest. Spreads, rolls and late updates blur it.",
    "High volume relative to open interest can be closing, rolling, spreading or hedging. Treat every label as a lead, not a fact.",
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
        fict = self.provider.fictional
        day = session_day(now)
        out: dict[str, Any] = {"as_of": now.isoformat(), "session_day": day.isoformat(), "fictional": fict, "source": self.provider.name,
                               "active_names": [], "option_names": [], "unusual": [], "follow_ups": [], "errors": [],
                               "thresholds": {"min_volume": MIN_UNUSUAL_VOLUME, "min_volume_oi_ratio": MIN_VOLUME_OI_RATIO,
                                              "min_volume_when_oi_zero_or_missing": MIN_ZERO_OI_VOLUME,
                                              "low_oi_below": LOW_OI, "min_volume_when_oi_low": MIN_LOW_OI_VOLUME,
                                              "relative_volume_surge": RELATIVE_VOLUME_SURGE,
                                              "oi_confirm_fraction": OI_CONFIRM_FRACTION},
                               "limitations": list(LIMITATIONS)}
        try:
            raw = self.provider.daily_bars(self.universe)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001 - say so, never fabricate a ranking
            out["errors"].append(f"daily bars unavailable: {type(exc).__name__}: {str(exc)[:100]}")
            self.store.record_scan(now, fict, out)
            return out
        ranked = rank_active(raw, now, top=0)
        out["active_names"] = ranked[:TOP_ACTIVE]
        out["heat_map"] = heat_map(ranked)
        prior = self.store.unusual_before(day.isoformat(), fict)
        # earlier unusual names come first: those are the ones whose open interest answers "did it stick"
        revisit: dict[str, float] = {}
        for p in prior.values():
            revisit[p["symbol"]] = max(revisit.get(p["symbol"], 0.0), p.get("score") or 0.0)
        pick = sorted(revisit, key=lambda sym: -revisit[sym])[:CHAINS_FOR_FOLLOW_UP]
        pick += [r["symbol"] for r in ranked[:CHAINS_BY_DOLLAR_VOLUME] if r["symbol"] not in pick]
        surging = sorted((r for r in ranked if r["surge"] and r["symbol"] not in pick), key=lambda r: -(r["relative_volume"] or 0))
        pick += [r["symbol"] for r in surging[:CHAINS_BY_RELATIVE_VOLUME]]
        scanned = failed = 0
        for sym in pick:
            if time.monotonic() - t0 > self.budget_s:
                out["errors"].append(f"time budget reached after {scanned} chains")
                break
            try:
                checked = check_snapshot(self.provider.snapshot_window(sym, SCAN_MIN_DTE, SCAN_MAX_DTE, SCAN_EXPIRIES), now)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                out["errors"].append(f"{sym}: chain unavailable ({describe_exc(exc)})")
                continue
            if checked.snapshot is None:
                failed += 1
                out["errors"].append(f"{sym}: chain rejected by the data-quality gate ({checked.issues[-1].kind if checked.issues else 'unknown'})")
                continue
            rows = unusual_contracts(checked.snapshot, now)
            out["unusual"].extend(rows)
            out["follow_ups"].extend(follow_ups(checked.snapshot, prior, now, day))
            out["option_names"].append({**option_totals(checked.snapshot, len(rows)), "sector": SECTOR_OF.get(sym)})
            scanned += 1
        annotate_with_history(out["unusual"], prior, self.store, day, fict)
        self.store.record_unusual(day.isoformat(), fict, out["unusual"][:400])
        out["unusual"].sort(key=lambda r: (r["decision"] != "REVIEWABLE", -r["score"], -r["volume"]))
        out["unusual_total"] = len(out["unusual"])
        out["sentiment"] = sentiment(ranked, out["option_names"], out["unusual"])
        out["unusual"] = out["unusual"][:MAX_UNUSUAL_ROWS]
        out["follow_ups"].sort(key=lambda f: (f["oi_verdict"] != "OI_ROSE", -(f.get("prior_score") or 0)))
        out["follow_ups"] = out["follow_ups"][:MAX_FOLLOW_UPS]
        out["option_names"].sort(key=lambda r: -r["total_volume"])
        out["coverage"] = {"universe": len(self.universe), "ranked": len(ranked), "chains_scanned": scanned, "chains_failed": failed,
                           "chains_planned": len(pick), "follow_up_names": min(len(revisit), CHAINS_FOR_FOLLOW_UP),
                           "seconds": round(time.monotonic() - t0, 1)}
        self.store.record_scan(now, fict, out)
        return out

    def latest(self) -> Optional[dict[str, Any]]:
        return self.store.latest_scan(self.provider.fictional)

    def status(self) -> dict[str, Any]:
        latest = self.latest()
        return {"running": self.running(), "last_error": self.last_error, "last_scan_at": latest["as_of"] if latest else None}
