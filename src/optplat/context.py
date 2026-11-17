"""Market context for the owner: option sentiment, gamma levels and expected moves on the index funds and mega-caps.

Display and research only. Nothing here feeds a strategy, sizing, risk or an order. Every figure is a description of a
delayed, sampled free-data option chain, not a forecast, and none is validated (see ``docs/SIGNALS.md``).

* Sentiment: calls against puts, by volume, by open interest and by premium. A fixed, pre-declared reading is attached
  (``CALL_HEAVY`` / ``BALANCED`` / ``PUT_HEAVY``). On index funds put volume is mostly hedging, so a put-heavy reading
  there is NOT called bearish; the group note says so.
* Gamma levels: per-strike modeled exposure (calls +, puts -, an invented inventory convention, see ``gex.py``), the
  call wall (largest positive strike at or above spot), the put wall (largest negative strike at or below spot) and the
  modeled gamma flip (``signals.gex`` revalues the chain at nearby spots).
* Expected move: the at-the-money straddle of the nearest usable expiry, as a percent of spot. It is what the option
  market charges, not what will happen.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Optional

from .marketdata import MarketSnapshot
from .models import Right
from .signals import bs_gamma, gex as signals_gex

INDEX_FUNDS = ("SPY", "QQQ", "IWM", "DIA")
MEGA_CAPS = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO")
CORE = INDEX_FUNDS + MEGA_CAPS
GROUPS = {"index": INDEX_FUNDS, "mega": MEGA_CAPS}

CALL_HEAVY_AT, PUT_HEAVY_AT = 1.3, 0.7   # display bins fixed in advance; not tuned on any result
MAX_STRIKES = 41
WINDOW = 0.15                            # strikes shown: within 15% of spot
MIN_STRADDLE_DTE = 3


def _num(x: Any) -> float:
    return float(x) if isinstance(x, (int, float)) and math.isfinite(x) else 0.0


def reading(ratio: Optional[float]) -> str:
    if ratio is None:
        return "UNKNOWN"
    return "CALL_HEAVY" if ratio >= CALL_HEAVY_AT else "PUT_HEAVY" if ratio <= PUT_HEAVY_AT else "BALANCED"


def _ratio(a: float, b: float) -> Optional[float]:
    return round(a / b, 3) if b > 0 else None


def sentiment_row(snap: MarketSnapshot) -> dict[str, Any]:
    cv = pv = coi = poi = 0.0
    cprem = pprem = 0.0
    for r in snap.rows:
        vol, oi = _num(r.volume), _num(r.open_interest)
        mid = (r.bid + r.ask) / 2 if r.bid > 0 and r.ask >= r.bid else 0.0
        prem = mid * vol * r.contract.multiplier
        if r.contract.right is Right.CALL:
            cv, coi, cprem = cv + vol, coi + oi, cprem + prem
        else:
            pv, poi, pprem = pv + vol, poi + oi, pprem + prem
    ratio = _ratio(cv, pv)
    return {"call_volume": int(cv), "put_volume": int(pv), "call_put_volume_ratio": ratio,
            "call_put_oi_ratio": _ratio(coi, poi), "call_premium_usd": round(cprem), "put_premium_usd": round(pprem),
            "call_put_premium_ratio": _ratio(cprem, pprem), "reading": reading(ratio)}


def expected_move(snap: MarketSnapshot, today: date) -> dict[str, Any]:
    """At-the-money straddle of the nearest expiry at least MIN_STRADDLE_DTE away, as a percent of spot."""
    spot = snap.underlying
    best = None
    for r in snap.rows:
        dte = (r.contract.expiry - today).days
        if dte < MIN_STRADDLE_DTE or spot <= 0 or r.bid <= 0 or r.ask < r.bid:
            continue
        key = (dte, abs(r.contract.strike - spot), r.contract.strike)
        if best is None or key < best[0]:
            best = (key, r.contract.expiry, r.contract.strike)
    if best is None:
        return {"status": "NO_USABLE_EXPIRY", "pct": None}
    _, expiry, strike = best
    mids = {}
    for r in snap.rows:
        if r.contract.expiry == expiry and r.contract.strike == strike and r.bid > 0 and r.ask >= r.bid:
            mids[r.contract.right] = (r.bid + r.ask) / 2
    if len(mids) < 2:
        return {"status": "INCOMPLETE_STRADDLE", "pct": None, "expiry": expiry.isoformat(), "strike": strike}
    pct = round((mids[Right.CALL] + mids[Right.PUT]) / spot * 100, 2)
    return {"status": "OK", "pct": pct, "expiry": expiry.isoformat(), "strike": strike, "dte": (expiry - today).days}


def levels(snap: MarketSnapshot, now: datetime) -> dict[str, Any]:
    """Per-strike modeled gamma exposure within WINDOW of spot, plus the call wall, put wall and gamma flip."""
    spot = snap.underlying
    calls: dict[float, float] = {}
    puts: dict[float, float] = {}
    used = skipped = 0
    for r in snap.rows:
        dte = (r.contract.expiry - now.date()).days
        k = r.contract.strike
        if (spot <= 0 or k <= 0 or dte < 1 or not r.iv or not r.open_interest or r.iv > 3.0
                or abs(k / spot - 1) > WINDOW):
            skipped += 1
            continue
        g = bs_gamma(spot, k, dte / 365, r.iv)
        if g is None:
            skipped += 1
            continue
        exposure = g * r.open_interest * r.contract.multiplier * spot * spot * 0.01 / 1e6  # USD millions per 1% move
        book = calls if r.contract.right is Right.CALL else puts
        book[k] = book.get(k, 0.0) + exposure
        used += 1
    strikes = sorted(set(calls) | set(puts))
    if len(strikes) > MAX_STRIKES:  # keep the strikes with the most exposure, then restore order
        strikes = sorted(sorted(strikes, key=lambda k: -(calls.get(k, 0) + puts.get(k, 0)))[:MAX_STRIKES])
    profile = [{"strike": k, "call_musd": round(calls.get(k, 0.0), 3), "put_musd": round(-puts.get(k, 0.0), 3),
                "net_musd": round(calls.get(k, 0.0) - puts.get(k, 0.0), 3)} for k in strikes]
    above = [p for p in profile if p["strike"] >= spot and p["call_musd"] > 0]
    below = [p for p in profile if p["strike"] <= spot and p["put_musd"] < 0]
    sig = signals_gex(snap, now)
    return {
        "spot": spot, "profile": profile, "rows_used": used, "rows_skipped": skipped,
        "call_wall": max(above, key=lambda p: (p["call_musd"], -p["strike"]))["strike"] if above else None,
        "put_wall": min(below, key=lambda p: (p["put_musd"], p["strike"]))["strike"] if below else None,
        "gamma_flip": sig["zero_gamma_spot"], "net_musd": round(sum(p["net_musd"] for p in profile), 3),
        "gross_musd": round(sum(p["call_musd"] - p["put_musd"] for p in profile), 3),
    }


def build_symbol(snap: MarketSnapshot, now: datetime) -> dict[str, Any]:
    lv = levels(snap, now)
    spot = snap.underlying
    gross = lv["gross_musd"]
    return {"symbol": snap.symbol, "spot": spot, "as_of": snap.as_of.isoformat(),
            "closes": [round(c, 2) for c in snap.closes[-40:] if isinstance(c, (int, float)) and math.isfinite(c)], "sentiment": sentiment_row(snap),
            "expected_move": expected_move(snap, now.date()), "levels": lv,
            # net as a share of gross is comparable across names of different size; sign is the assumption's
            "net_share_of_gross": round(lv["net_musd"] / gross, 3) if gross else None,
            "flip_distance_pct": round((lv["gamma_flip"] / spot - 1) * 100, 2) if lv["gamma_flip"] and spot > 0 else None}


def group_summary(rows: list[dict[str, Any]], symbols: tuple[str, ...]) -> dict[str, Any]:
    pick = [r for r in rows if r["symbol"] in symbols]
    cv = sum(r["sentiment"]["call_volume"] for r in pick)
    pv = sum(r["sentiment"]["put_volume"] for r in pick)
    cp = sum(r["sentiment"]["call_premium_usd"] for r in pick)
    pp = sum(r["sentiment"]["put_premium_usd"] for r in pick)
    ratio = _ratio(cv, pv)
    return {"names": len(pick), "of": len(symbols), "call_volume": cv, "put_volume": pv, "call_put_volume_ratio": ratio,
            "call_put_premium_ratio": _ratio(cp, pp), "reading": reading(ratio),
            "call_heavy_names": sum(r["sentiment"]["reading"] == "CALL_HEAVY" for r in pick),
            "put_heavy_names": sum(r["sentiment"]["reading"] == "PUT_HEAVY" for r in pick)}


NOTES = (
    "Sentiment here is option volume only. Index-fund put volume is mostly hedging, so a put-heavy index is not by itself bearish.",
    "Call and put walls and the gamma flip use open interest and a sign convention, not observed dealer positions.",
    "Chains are a delayed, sampled free-data view (nearest expirations only), so totals are partial.",
    "Expected move is the at-the-money straddle of the nearest expiry: what the options market charges, not a forecast.",
    "Descriptive only. Nothing here is validated or used by any strategy, lane, risk check or order.",
)


def build(snaps: list[MarketSnapshot], now: datetime, fictional: bool) -> dict[str, Any]:
    """One entry per core symbol that was read this scan. Never raises on a bad chain: it is skipped and named."""
    rows, errors = [], []
    for snap in snaps:
        try:
            rows.append(build_symbol(snap, now))
        except Exception as exc:  # noqa: BLE001 - display only
            errors.append(f"{snap.symbol}: {type(exc).__name__}")
    rows.sort(key=lambda r: (CORE.index(r["symbol"]) if r["symbol"] in CORE else 99, r["symbol"]))
    return {"as_of": now.isoformat(), "fictional": fictional, "rows": rows, "errors": errors,
            "groups": {name: group_summary(rows, syms) for name, syms in GROUPS.items()},
            "missing": [s for s in CORE if s not in {r["symbol"] for r in rows}], "notes": list(NOTES)}
