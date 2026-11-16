"""Read an OCC option symbol such as ``SPY   261211P00751000`` into parts a person can read.

Anything that does not parse returns None; callers then show the raw text rather than guess.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

_OCC = re.compile(r"^\s*([A-Z.\-]{1,6}?)\s*(\d{2})(\d{2})(\d{2})([CP])(\d{8})\s*$")


def parse_occ(occ: Optional[str]) -> Optional[dict[str, Any]]:
    m = _OCC.match(occ or "")
    if not m:
        return None
    sym, yy, mm, dd, right, strike = m.groups()
    try:
        expiry = date(2000 + int(yy), int(mm), int(dd))
    except ValueError:
        return None
    return {"symbol": sym, "expiry": expiry.isoformat(), "right": right, "strike": int(strike) / 1000}


def _strike_text(strike: float) -> str:
    return f"{strike:g}"


def contract_label(symbol: str, right: str, strike: float, expiry: str) -> str:
    """"SPY put 751 · Dec 11 2026" - the same wording the dashboard uses."""
    try:
        d = date.fromisoformat(expiry)
        when = f"{d.strftime('%b')} {d.day} {d.year}"
    except ValueError:
        when = str(expiry)
    return f"{symbol} {'call' if right == 'C' else 'put'} {_strike_text(strike)} · {when}"
