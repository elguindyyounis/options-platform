"""Modeled net gamma exposure (GEX) from a chain sample. Research context only.

Open interest does NOT reveal dealer positioning. By convention calls count as positive and puts as
negative gamma; that is an INVENTED INVENTORY ASSUMPTION, the same one the options-alerter's
``gex.py`` makes. The platform's chain is a sample, not the full chain, so totals are partial.
Units: Black-Scholes gamma * OI * multiplier * spot^2 * 0.01, in USD millions per 1% move.
Display only: nothing here feeds strategy, sizing, risk or orders.
"""
from __future__ import annotations

from math import exp, isfinite, log, pi, sqrt
from typing import Any

from .marketdata import MarketSnapshot

RATE = 0.04  # same fixed rate as the alerter, so numbers are comparable
MAX_DTE = 45

ASSUMPTIONS = (
    "Calls are counted positive and puts negative by convention; this is NOT observed dealer positioning.",
    "Built from the chain sample the provider returned, not the full chain: totals are partial.",
    "Open interest and IV can be delayed or missing; rows without them are skipped and counted.",
    "Contracts expiring today use a one-day floor; no intraday or true 0DTE flows.",
    "Research context only, not a prediction or a reason to trade.",
)


def _gamma(spot: float, strike: float, t: float, iv: float) -> float | None:
    try:
        d1 = (log(spot / strike) + (RATE + iv * iv / 2) * t) / (iv * sqrt(t))
        g = exp(-d1 * d1 / 2) / (sqrt(2 * pi) * spot * iv * sqrt(t))
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return g if isfinite(g) else None


def net_gex(snap: MarketSnapshot) -> dict[str, Any]:
    """Return a labelled net-GEX summary for one snapshot. Never raises on bad rows."""
    today = snap.as_of.date()
    by_strike: dict[float, float] = {}
    used = skipped = 0
    for row in snap.rows:
        c = row.contract
        days = (c.expiry - today).days
        iv, oi = row.iv, row.open_interest
        if (
            days < 0 or days > MAX_DTE or iv is None or oi is None
            or not (isfinite(iv) and 0 < iv < 10) or oi <= 0 or c.strike <= 0 or snap.underlying <= 0
        ):
            skipped += 1
            continue
        g = _gamma(snap.underlying, c.strike, max(days, 1) / 365.25, iv)
        if g is None:
            skipped += 1
            continue
        exposure = g * oi * c.multiplier * snap.underlying ** 2 * 0.01 / 1e6
        sign = 1.0 if c.right.value == "C" else -1.0
        by_strike[c.strike] = by_strike.get(c.strike, 0.0) + sign * exposure
        used += 1
    out: dict[str, Any] = {
        "symbol": snap.symbol,
        "as_of": snap.as_of.isoformat(),
        "source": snap.source,
        "fictional": snap.fictional,
        "model": "ASSUMED_CALL_PLUS_PUT_MINUS_V1",
        "units": "USD millions per 1% move",
        "rows_used": used,
        "rows_skipped": skipped,
        "net_gex_musd": None,
        "largest_positive_strike": None,
        "largest_negative_strike": None,
    }
    if used:
        out["net_gex_musd"] = round(sum(by_strike.values()), 4)
        hi = max(by_strike, key=lambda k: (by_strike[k], -k))
        lo = min(by_strike, key=lambda k: (by_strike[k], k))
        out["largest_positive_strike"] = hi if by_strike[hi] > 0 else None
        out["largest_negative_strike"] = lo if by_strike[lo] < 0 else None
    return out
