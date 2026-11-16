"""Unusual options turnover radar (research only). Ported in spirit from the alerter's ``unusual_activity.py``.

Flags single contracts whose reported daily volume is far above reported open interest, e.g. 65,000
contracts against 810 open. A free chain gives aggregate volume and prior-session open interest only.
It CANNOT tell who bought, whether a trade opened a position, ask/bid-side share, multi-leg share or
true executed premium. Those numbers on paid flow screens are not available here and are left null.
Premium is a scale at the QUOTED mid, not what was paid. Nothing here feeds strategy, sizing, risk
or orders: it is not a signal and not a claim of edge.
"""
from __future__ import annotations

from math import isfinite
from typing import Any

from .marketdata import MarketSnapshot

MIN_VOLUME = 150
MIN_RATIO = 3.0
MIN_ZERO_OI_VOLUME = 500
MAX_ROWS_PER_SYMBOL = 5

# Hand-written assumption, not a data feed: names that tend to move together. Used only to say
# "the same theme shows up in more than one name". Edit it as the owner sees fit.
RELATED_GROUPS: dict[str, tuple[str, ...]] = {
    "semiconductors": ("SMH", "SOXX", "NVDA", "AMD", "AVGO", "MU", "TSM", "INTC", "QCOM", "SMCI", "ASML", "AMAT", "LRCX"),
    "broad market": ("SPY", "QQQ", "IWM", "DIA", "SPX", "SPCX"),
}

CAVEATS = (
    "Volume is the day's total and open interest is the prior session's: this is not a trade tape.",
    "Aggressor side, opening vs closing, multi-leg share and true premium are NOT available here (shown as not available).",
    "A large put or call can be a hedge, a spread leg or a lottery ticket; direction is not known.",
    "Research context only. It never creates an order and is not evidence of any edge.",
)


def group_of(symbol: str) -> str | None:
    s = symbol.upper()
    for name, members in RELATED_GROUPS.items():
        if s in members:
            return name
    return None


def _tier(volume: int, oi: int | None, ratio: float | None) -> str:
    if ratio is not None and ((ratio >= 20 and volume >= 5000 and (oi or 0) >= 100) or (ratio >= 50 and volume >= 1500 and (oi or 0) >= 25)):
        return "EXTREME"
    if (ratio is not None and ((ratio >= 8 and volume >= 500) or (ratio >= 4 and volume >= 10000))) or (ratio is None and volume >= 10000):
        return "HIGH"
    return "ELEVATED"


def scan_flow(snap: MarketSnapshot) -> list[dict[str, Any]]:
    """Return up to MAX_ROWS_PER_SYMBOL unusual-turnover observations. Never raises on bad rows."""
    today = snap.as_of.date()
    out: list[dict[str, Any]] = []
    for row in snap.rows:
        vol, oi = row.volume, row.open_interest
        if vol is None or vol < MIN_VOLUME:
            continue
        if oi is not None and oi < 0:
            oi = None
        ratio = round(vol / oi, 1) if oi else None
        if ratio is not None and ratio < MIN_RATIO:
            continue
        if ratio is None and vol < MIN_ZERO_OI_VOLUME:
            continue
        if not (isfinite(row.bid) and isfinite(row.ask)) or row.ask <= 0 or not 0 <= row.bid <= row.ask:
            mid = None
        else:
            mid = (row.bid + row.ask) / 2
        c = row.contract
        if snap.underlying > 0 and c.strike > 0:
            raw = (snap.underlying - c.strike) / snap.underlying if c.right.value == "P" else (c.strike - snap.underlying) / snap.underlying
            otm = round(max(0.0, raw) * 100, 1)
        else:
            otm = None
        dte = (c.expiry - today).days
        flags = []
        if ratio is not None and ratio >= 20:
            flags.append("volume at least 20x open interest")
        if 0 <= dte <= 10:
            flags.append("10 or fewer days to expiry")
        if otm is not None and otm >= 20:
            flags.append("20%+ out of the money")
        if oi is None or oi == 0:
            flags.append("open interest missing or zero: ratio undefined")
        out.append({
            "symbol": snap.symbol, "contract": c.occ_symbol.strip(), "right": c.right.value, "strike": c.strike,
            "expiry": c.expiry.isoformat(), "dte": dte, "otm_pct": otm, "volume": vol, "open_interest": oi,
            "volume_oi_ratio": ratio, "tier": _tier(vol, oi, ratio),
            "premium_at_quoted_mid_usd": round(mid * vol * c.multiplier) if mid is not None else None,
            "premium_basis": "volume x quoted mid x multiplier: a scale, not what was paid",
            "ask_side_pct": None, "multi_leg_pct": None, "opening_trade_verified": False,
            "flags": flags, "group": group_of(snap.symbol), "fictional": snap.fictional, "source": snap.source,
            "observe_only": True,
        })
    rank = {"EXTREME": 0, "HIGH": 1, "ELEVATED": 2}
    out.sort(key=lambda r: (rank[r["tier"]], -(r["premium_at_quoted_mid_usd"] or 0), r["contract"]))
    return out[:MAX_ROWS_PER_SYMBOL]


def related_themes(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group flagged observations by theme; report themes where 2+ different symbols were flagged."""
    seen: dict[str, dict[str, list[str]]] = {}
    for r in rows:
        if r.get("group"):
            seen.setdefault(r["group"], {}).setdefault(r["symbol"], []).append(r["contract"])
    return [
        {"group": g, "symbols": sorted(m), "note": "Same theme in several names. Correlated, so not independent evidence."}
        for g, m in sorted(seen.items()) if len(m) >= 2
    ]
