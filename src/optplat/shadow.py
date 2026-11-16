"""The shadow book: follow candidates whether or not anything was bought, and keep their bid path.

Evolution plan, Phase 1 item 1. Every scan, for each chain it reads, this module picks a few liquid contracts
(``select``) and records them once per day with the features known at that moment. On every later scan that reads the
same contract it appends a point to the contract's path (bid, ask, underlying), at every scan for the first ten
trading days and once a day after that, out to thirty. Entry is always the ask when followed and exit the bid on a path
point, so any exit rule can be replayed later over the recorded bids (the replay harness is a later step).

Research only. Nothing here places an order, changes a threshold or feeds a strategy. The selection is deliberately
simple and generic (most active liquid contracts per underlying): following the top candidates of each strategy and lane
is a later step. IV percentile and days to earnings are not recorded yet and are listed in ``missing_features`` so no
analysis can mistake them for zero.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from .market_clock import NY
from .marketdata import ChainRow, MarketSnapshot
from .tracker import trading_days_between
from .universe import SECTOR_OF

PER_UNDERLYING = 6        # contracts followed per underlying per day
MIN_DTE, MAX_DTE = 7, 120
MAX_SPREAD_PCT = 25.0     # wider than this is not a price anyone would pay; it would only add noise
DENSE_DAYS = 10           # a path point at every scan for this many trading days, then one per day
MAX_AGE = 30              # trading days followed
SLACK = 2
MISSING_FEATURES = ["iv_percentile", "days_to_earnings"]
GATE = {"trading_days": 20, "followed": 2000, "underlyings": 50, "complete_pct": 80.0, "export_days_in_a_row": 5}


def spread_pct(row: ChainRow) -> Optional[float]:
    mid = (row.bid + row.ask) / 2
    return None if row.bid <= 0 or row.ask <= 0 or row.ask < row.bid or mid <= 0 else round((row.ask - row.bid) / mid * 100, 2)


def select(snap: MarketSnapshot, day: date) -> list[ChainRow]:
    """Liquid, plausibly priced contracts, most active first, at most PER_UNDERLYING."""
    ok = []
    for r in snap.rows:
        sp = spread_pct(r)
        dte = (r.contract.expiry - day).days
        if sp is None or sp > MAX_SPREAD_PCT or not MIN_DTE <= dte <= MAX_DTE:
            continue
        ok.append((-(r.volume or 0), sp, r.contract.occ_symbol, r))
    ok.sort(key=lambda t: t[:3])
    return [t[3] for t in ok[:PER_UNDERLYING]]


def features(snap: MarketSnapshot, row: ChainRow, day: date, now: datetime) -> dict[str, Any]:
    c, u = row.contract, snap.underlying
    local = now.astimezone(NY)
    return {"symbol": snap.symbol, "contract": c.occ_symbol.strip(), "right": c.right.value, "strike": c.strike, "expiry": c.expiry.isoformat(),
            "dte": (c.expiry - day).days, "moneyness_pct": round((c.strike / u - 1) * 100, 2) if u > 0 else None,
            "underlying_price": u, "entry_ask": row.ask, "entry_bid": row.bid, "spread_pct": spread_pct(row), "iv": row.iv,
            "volume": row.volume, "open_interest": row.open_interest,
            "trend_pct": round((u / (sum(snap.closes) / len(snap.closes)) - 1) * 100, 2) if snap.closes and sum(snap.closes) > 0 else None,
            "sector": SECTOR_OF.get(snap.symbol), "hour_et": round(local.hour + local.minute / 60, 2), "followed_at": now.isoformat(),
            "source": snap.source, "verified": snap.timestamp_verified, "missing_features": MISSING_FEATURES}


def point_due(age: int, observed_days: set[str], day: date) -> bool:
    """Dense for the first DENSE_DAYS trading days, then one point per calendar day, up to MAX_AGE (+SLACK late)."""
    if age < 0 or age > MAX_AGE + SLACK:
        return False
    return age <= DENSE_DAYS or day.isoformat() not in observed_days


def observe(store: Any, snap: MarketSnapshot, day: date, now: datetime, fictional: bool) -> dict[str, int]:
    """Follow new candidates from this chain and extend the paths of contracts already followed. Never raises on bad rows."""
    followed = points = 0
    for row in select(snap, day):
        if store.record_shadow_follow(row.contract.occ_symbol.strip(), day.isoformat(), fictional, features(snap, row, day, now)):
            followed += 1
    by_contract = {r.contract.occ_symbol.strip(): r for r in snap.rows}
    seen = store.shadow_observed_days(snap.symbol, fictional)
    for f in store.shadow_follows(snap.symbol, day.isoformat(), fictional):
        row = by_contract.get(f["contract"])
        if row is None or now.isoformat() <= f["followed_at"] or row.bid < 0:
            continue  # contract missing from this chain, or this is the scan that followed it
        age = trading_days_between(date.fromisoformat(f["followed_day"]), day)
        if point_due(age, seen.get((f["contract"], f["followed_day"]), set()), day):
            if store.record_shadow_point(f["contract"], f["followed_day"], fictional, now.isoformat(), day.isoformat(),
                                         {"age": age, "bid": row.bid, "ask": row.ask, "underlying": snap.underlying,
                                          "volume": row.volume, "open_interest": row.open_interest, "iv": row.iv}):
                points += 1
    return {"followed": followed, "points": points}


def report(store: Any, fictional: bool, today: date) -> dict[str, Any]:
    """Progress towards the Phase 1 gate. 'Complete' means the path reaches the 30 trading day mark or the contract has expired."""
    follows = store.shadow_all_follows(fictional)
    ages: dict[tuple[str, str], int] = {}
    for p in store.shadow_all_points(fictional):
        k = (p["contract"], p["followed_day"])
        ages[k] = max(ages.get(k, 0), p["age"])
    complete = sum(1 for f in follows if ages.get((f["contract"], f["followed_day"]), 0) >= MAX_AGE
                   or (date.fromisoformat(f["expiry"]) < today and (f["contract"], f["followed_day"]) in ages))
    days = len({f["followed_day"] for f in follows})
    syms = len({f["symbol"] for f in follows})
    pct = round(complete / len(follows) * 100, 1) if follows else None
    status = {"trading_days": days, "followed": len(follows), "underlyings": syms, "complete_pct": pct}
    met = {k: (status[k] is not None and status[k] >= GATE[k]) for k in status}
    return {"fictional": fictional, **status, "points": sum(1 for _ in ages), "gate": GATE, "gate_met": met,
            "gate_met_except_export": all(met.values()),  # the export streak is not visible from here
            "note": "Gate also needs the export to run five days in a row, which this report cannot see; the owner or the weekly agent confirms it. "
                    "Selection is generic (most active liquid contracts per underlying); per-strategy candidates are not followed yet.",
            "missing_features": MISSING_FEATURES}
