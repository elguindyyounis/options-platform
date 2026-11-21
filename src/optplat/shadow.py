"""The shadow book: follow candidates whether or not anything was bought, and keep their bid path.

Evolution plan, Phase 1 item 1. Every scan, for each chain it reads, this module picks a few liquid contracts
(``select``) and records them once per day with the features known at that moment. On every later scan that reads the
same contract it appends a point to the contract's path (bid, ask, underlying), at every scan for the first ten
trading days and once a day after that, out to thirty. Entry is always the ask when followed and exit the bid on a path
point, so any exit rule can be replayed later over the recorded bids (the replay harness is a later step).

Research only. Nothing here places an order, changes a threshold or feeds a strategy. The selection is deliberately
simple and generic (most active liquid contracts per underlying): following the top candidates of each strategy and lane
is a later step. A feature that could not be measured is listed in ``missing_features`` so no analysis can mistake it for
zero. Days to earnings comes from the event calendar (Yahoo's unofficial dates, often estimates) and is labelled as such.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from .events import ETFS
from .market_clock import NY
from .marketdata import ChainRow, MarketSnapshot
from .tracker import trading_days_between
from .universe import SECTOR_OF

TOP_PER_STRATEGY = 3      # each strategy's best-ranked proposals followed per underlying per scan (Phase 1 item 1a)
PER_UNDERLYING = 6        # contracts followed per underlying per day
MIN_DTE, MAX_DTE = 7, 120
MAX_SPREAD_PCT = 25.0     # wider than this is not a price anyone would pay; it would only add noise
DENSE_DAYS = 10           # a path point at every scan for this many trading days, then one per day
MAX_AGE = 30              # trading days followed
SLACK = 2
MISSING_FEATURES = ["iv_percentile", "days_to_earnings"]  # each is dropped from a row once it is measured (iv_percentile needs MIN_IV_HISTORY prior days)
MIN_IV_HISTORY = 20       # prior days of a name's own IV level needed before a percentile means anything
ATM_BAND_PCT = 5.0        # contracts within this moneyness band define the name's IV level
GATE = {"trading_days": 20, "followed": 2000, "underlyings": 50, "complete_pct": 80.0, "export_days_in_a_row": 5}


def is_callout(follow: dict[str, Any]) -> bool:
    """A follow entered by hand from another person's alert (see callouts.py), not picked by the scan."""
    return str(follow.get("source", "")).startswith("callout:")


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


def name_iv(snap: MarketSnapshot, day: date) -> Optional[float]:
    """The name's IV level now: median IV of near-the-money contracts 7 to 120 days out. None when the chain gives too few."""
    u = snap.underlying
    vals = sorted(r.iv for r in snap.rows if r.iv and r.iv > 0 and u > 0 and abs(r.contract.strike / u - 1) * 100 <= ATM_BAND_PCT
                  and MIN_DTE <= (r.contract.expiry - day).days <= MAX_DTE)
    if len(vals) < 3:
        return None
    mid = len(vals) // 2
    return round(vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2, 4)


def iv_percentile(current: Optional[float], history: dict[str, float]) -> Optional[float]:
    """Share (0 to 100) of this name's earlier daily IV levels that sit below today's. None until MIN_IV_HISTORY days exist."""
    if current is None or len(history) < MIN_IV_HISTORY:
        return None
    return round(sum(1 for v in history.values() if v < current) / len(history) * 100, 1)


def earnings_context(calendar: Any, symbol: str, day: date) -> Optional[dict[str, Any]]:
    """Point-in-time earnings facts for hypotheses E2/E4/E6, or None when they could not be measured (never a guess).

    Looks MAX_DTE days ahead. ``earnings_status`` is "known" (next date and days to it), "etf" (no earnings by nature) or
    "none_in_window" (a source answered but nothing falls inside the window). The dates are unofficial estimates.
    """
    if calendar is None:
        return None
    try:
        events = calendar.earnings(symbol, day, day + timedelta(days=MAX_DTE))
    except Exception:  # noqa: BLE001 - research only
        return None
    if events is None:
        return None
    if symbol.upper() in ETFS:
        return {"earnings_status": "etf", "days_to_earnings": None, "next_earnings": None}
    if not events:
        return {"earnings_status": "none_in_window", "days_to_earnings": None, "next_earnings": None}
    nxt = min(e.day for e in events)
    return {"earnings_status": "known", "days_to_earnings": (nxt - day).days, "next_earnings": nxt.isoformat(),
            "earnings_source": "unofficial estimate"}


def last_earnings(history: list[dict[str, Any]], day: date) -> Optional[dict[str, Any]]:
    """Most recent earnings date that passed, taken from this name's own earlier follows (hypothesis E6 needs days SINCE a report).

    The calendar source only lists upcoming dates, so a report date is learned from an earlier follow's ``next_earnings`` once
    that date is in the past (and was never later than ``day``). It is an earlier unofficial estimate, labelled as such, and
    None when no earlier follow of this name carried a date that has passed. Never a guess.
    """
    dates = []
    for f in history:
        try:
            d = date.fromisoformat(str(f.get("next_earnings")))
        except ValueError:
            continue
        if d <= day:
            dates.append(d)
    if not dates:
        return None
    last = max(dates)
    return {"last_earnings": last.isoformat(), "days_since_earnings": (day - last).days, "last_earnings_source": "earlier shadow-book estimate"}


def return_5d_pct(closes: tuple[float, ...]) -> Optional[float]:
    """Return over the last 5 daily bars of the snapshot, in percent; None when there are fewer than 6 bars. E6 buckets on this."""
    if len(closes) < 6 or closes[-6] <= 0:
        return None
    return round((closes[-1] / closes[-6] - 1) * 100, 2)


def features(snap: MarketSnapshot, row: ChainRow, day: date, now: datetime, nv: Optional[float] = None, ivp: Optional[float] = None,
             earn: Optional[dict[str, Any]] = None, since: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    c, u = row.contract, snap.underlying
    local = now.astimezone(NY)
    return {"symbol": snap.symbol, "contract": c.occ_symbol.strip(), "right": c.right.value, "strike": c.strike, "expiry": c.expiry.isoformat(),
            "dte": (c.expiry - day).days, "moneyness_pct": round((c.strike / u - 1) * 100, 2) if u > 0 else None,
            "underlying_price": u, "entry_ask": row.ask, "entry_bid": row.bid, "spread_pct": spread_pct(row), "iv": row.iv,
            "volume": row.volume, "open_interest": row.open_interest,
            "trend_pct": round((u / (sum(snap.closes) / len(snap.closes)) - 1) * 100, 2) if snap.closes and sum(snap.closes) > 0 else None,
            "sector": SECTOR_OF.get(snap.symbol), "hour_et": round(local.hour + local.minute / 60, 2), "followed_at": now.isoformat(),
            "source": snap.source, "verified": snap.timestamp_verified, "name_iv": nv,
            "missing_features": [m for m in MISSING_FEATURES if not ((m == "iv_percentile" and ivp is not None) or (m == "days_to_earnings" and earn is not None))],
            **({"iv_percentile": ivp} if ivp is not None else {}), **(earn or {}), **(since or {}),
            **({"return_5d_pct": r5} if (r5 := return_5d_pct(snap.closes)) is not None else {})}


def point_due(age: int, observed_days: set[str], day: date) -> bool:
    """Dense for the first DENSE_DAYS trading days, then one point per calendar day, up to MAX_AGE (+SLACK late)."""
    if age < 0 or age > MAX_AGE + SLACK:
        return False
    return age <= DENSE_DAYS or day.isoformat() not in observed_days


def strategy_picks(strategies: Any, snap: MarketSnapshot, now: datetime) -> list[tuple[ChainRow, dict[str, Any]]]:
    """The top TOP_PER_STRATEGY proposals of each strategy on this chain, with the strategy, version, rank and score that chose them.

    Evolution plan Phase 1 item 1(a): follow what each strategy would have bought whether or not anything was bought, so
    S1 (does the ranking score predict anything) has the ranked list to compare against a random pick. A strategy that
    raises is skipped; a proposal whose contract is not in the chain is skipped, never guessed.
    """
    by_contract = {r.contract.occ_symbol.strip(): r for r in snap.rows}
    out: list[tuple[ChainRow, dict[str, Any]]] = []
    for strat in strategies:
        try:
            props = list(strat.propose(snap, now))[:TOP_PER_STRATEGY]
        except Exception:  # noqa: BLE001 - research only
            continue
        for rank, p in enumerate(props, 1):
            r = by_contract.get(p.contract.occ_symbol.strip())
            if r is not None:
                out.append((r, {"strategy": strat.name, "version": strat.version, "rank": rank, "score": p.score}))
    return out


def observe(store: Any, snap: MarketSnapshot, day: date, now: datetime, fictional: bool, strategies: Any = (), calendar: Any = None) -> dict[str, int]:
    """Follow new candidates from this chain and extend the paths of contracts already followed. Never raises on bad rows.

    ``strategies`` (optional) adds each strategy's top proposals to the followed set and tags every followed contract that a
    strategy chose with ``chosen_by``; the generic most-active selection still runs as before.
    """
    followed = points = 0
    nv = name_iv(snap, day)
    history: dict[str, float] = {}  # earlier days only, one level per day (the first recorded that day)
    for f in sorted(store.shadow_follows(snap.symbol, day.isoformat(), fictional), key=lambda f: f["followed_at"]):
        if f["followed_day"] < day.isoformat() and f.get("name_iv"):
            history.setdefault(f["followed_day"], f["name_iv"])
    ivp = iv_percentile(nv, history)
    earn = earnings_context(calendar, snap.symbol, day)
    since = last_earnings([f for f in store.shadow_follows(snap.symbol, day.isoformat(), fictional) if f["followed_day"] < day.isoformat()], day)
    for row in select(snap, day):
        if store.record_shadow_follow(row.contract.occ_symbol.strip(), day.isoformat(), fictional, features(snap, row, day, now, nv, ivp, earn, since)):
            followed += 1
    for row, tag in strategy_picks(strategies, snap, now):
        sym = row.contract.occ_symbol.strip()
        if store.record_shadow_follow(sym, day.isoformat(), fictional, features(snap, row, day, now, nv, ivp, earn, since)):
            followed += 1
        store.tag_shadow_follow(sym, day.isoformat(), fictional, tag)
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


def one_per_underlying_day(follows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Independent observations (evolution plan Phase 1 item 4): one followed contract per underlying per day.

    Several strikes of one name on one day move together, so counting each as a separate trade overstates the sample.
    The rule is fixed before any result exists: keep the most active contract (highest volume), ties broken by the
    contract symbol. Rows without a symbol or day are skipped, never guessed.
    """
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for f in follows:
        sym, day = f.get("symbol"), f.get("followed_day")
        if not sym or not day or is_callout(f):  # callouts are reported separately, never mixed into the generic sample
            continue
        key = (sym, day)
        rank = (-(f.get("volume") or 0), str(f.get("contract")))
        if key not in best or rank < (-(best[key].get("volume") or 0), str(best[key].get("contract"))):
            best[key] = f
    return [best[k] for k in sorted(best)]


def report(store: Any, fictional: bool, today: date) -> dict[str, Any]:
    """Progress towards the Phase 1 gate. 'Complete' means the path reaches the 30 trading day mark or the contract has expired."""
    all_follows = store.shadow_all_follows(fictional)
    follows = [f for f in all_follows if not is_callout(f)]  # callouts do not count towards the gate
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
    independent = len(one_per_underlying_day(follows))
    return {"fictional": fictional, "callouts_logged": len(all_follows) - len(follows), **status, "independent_observations": independent, "points": sum(1 for _ in ages), "gate": GATE, "gate_met": met,
            "gate_met_except_export": all(met.values()),  # the export streak is not visible from here
            "note": "Gate also needs the export to run five days in a row, which this report cannot see; the owner or the weekly agent confirms it. "
                    "The 'followed' count includes several strikes of one name per day; 'independent_observations' (one per underlying per day) is the sample any hypothesis test can claim. "
                    "Selection is the most active liquid contracts per underlying plus the top proposals of each strategy (tagged chosen_by); the five options lanes are not followed separately yet.",
            "missing_features": MISSING_FEATURES}
