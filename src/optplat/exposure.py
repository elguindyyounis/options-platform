"""Option greeks of the OPEN research-lane trades, summed. Display only.

Nothing here trades, sizes or exits anything. It answers "if the underlyings move, how much do the open lane trades move?"
Black-Scholes greeks, rate 0 and no dividends (the same rough assumptions as ``signals.bs_gamma``), per contract held:

* delta   shares of underlying the position behaves like (positive for calls, negative for puts)
* theta   dollars lost per calendar day to time passing, all else equal
* vega    dollars gained per one volatility point (1 IV point = 0.01) rise in implied volatility

Honest limits: the underlying price and implied volatility are the values recorded when each trade OPENED (the lane does
not store current ones), so the figures drift from reality as the market moves; only time to expiry is current. A trade
with a missing or implausible entry value is left out and counted, so a partial sum is never shown as the whole.
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Optional

from .models import Right
from .store import Store

MAX_IV = 3.0  # above 300% is a broken quote, the same cut-off the gamma model uses
MIN_DAYS = 0.5
NOTE = ("Black-Scholes, rate 0, no dividends. Underlying price and implied volatility are as of each trade's entry, "
        "not current; only time to expiry is current. Display only: nothing here changes a trade.")


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_greeks(right: Right, spot: float, strike: float, t_years: float, vol: float) -> Optional[dict[str, float]]:
    """Per-share greeks (rate 0). theta per day, vega per vol point. None when the inputs are unusable."""
    if not all(math.isfinite(x) for x in (spot, strike, t_years, vol)) or min(spot, strike, t_years, vol) <= 0:
        return None
    sq = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + vol * vol / 2 * t_years) / (vol * sq)
    pdf = math.exp(-d1 * d1 / 2) / math.sqrt(2 * math.pi)
    delta = _ncdf(d1) if right is Right.CALL else _ncdf(d1) - 1
    return {"delta": delta, "gamma": pdf / (spot * vol * sq),
            "theta_per_day": -spot * pdf * vol / (2 * sq) / 365.25, "vega_per_point": spot * pdf * sq / 100}


def trade_greeks(t: dict[str, Any], now: datetime) -> Optional[dict[str, Any]]:
    """Position greeks of one open lane trade, or None (with the caller counting it) when an input is missing."""
    o = t.get("open_payload") or {}
    try:
        right = Right(o["right"])
        strike = float(o["strike"])
        days = (date.fromisoformat(o["expiry"]) - now.date()).days
        spot = float(o.get("chain_underlying") or o.get("underlying_price") or 0)
        iv = float(o.get("iv") or 0)
        qty = int(t["quantity"])
        mult = int(o.get("multiplier") or 100)
    except (KeyError, TypeError, ValueError):
        return None
    if days < 0 or not (0 < iv < MAX_IV):
        return None
    g = bs_greeks(right, spot, strike, max(days, MIN_DAYS) / 365.25, iv)
    if g is None:
        return None
    n = qty * mult
    return {"id": t.get("id"), "symbol": t["symbol"], "contract": o.get("contract"), "right": right.value, "quantity": qty,
            "delta_shares": round(g["delta"] * n, 1), "gamma_shares_per_dollar": round(g["gamma"] * n, 2),
            "theta_usd_per_day": round(g["theta_per_day"] * n, 2), "vega_usd_per_point": round(g["vega_per_point"] * n, 2)}


def open_exposure(store: Store, lanes: list[str], fictional: bool, now: datetime) -> dict[str, Any]:
    """Sum the greeks of every open option trade in ``lanes``. ``unknown`` counts open trades that could not be valued."""
    rows: list[dict[str, Any]] = []
    unknown = 0
    for lane in lanes:
        for t in store.lane_trades(lane, fictional, 2000):
            if t["closed_at"] is not None or "expiry" not in (t.get("open_payload") or {}):
                continue  # closed, or a stock-lane trade (no greeks)
            g = trade_greeks(t, now)
            if g is None:
                unknown += 1
            else:
                rows.append({"lane": lane, **g})
    by_symbol: dict[str, float] = {}
    for r in rows:
        by_symbol[r["symbol"]] = by_symbol.get(r["symbol"], 0.0) + r["delta_shares"]
    total = lambda k: round(sum(r[k] for r in rows), 2)  # noqa: E731
    return {"fictional": fictional, "as_of": now.isoformat(), "valued": len(rows), "unknown": unknown,
            "complete": unknown == 0, "net_delta_shares": total("delta_shares"), "theta_usd_per_day": total("theta_usd_per_day"),
            "vega_usd_per_point": total("vega_usd_per_point"),
            "delta_by_symbol": {k: round(v, 1) for k, v in sorted(by_symbol.items())}, "trades": rows, "note": NOTE}
