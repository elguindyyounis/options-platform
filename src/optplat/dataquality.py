"""Data-quality gate. Bad data is dropped or rejected and logged, never repaired or guessed.

Every market snapshot passes through ``check_snapshot`` before any strategy, exit rule or simulated quote sees
it. Anything unknown or implausible means "do not use it". The checks only ever remove information, so they can
make the platform trade less, never more.

Severities:
  drop    a single chain row was removed
  reject  the whole snapshot is unusable (the engine treats the symbol as having no data this cycle)
  warn    suspicious but kept, and counted so it can be investigated
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Optional

from .marketdata import ChainRow, MarketSnapshot

MAX_SNAPSHOT_AGE_S = 900  # a snapshot older than this at the moment it is read is not a current picture
MAX_FUTURE_SKEW_S = 5
IV_RANGE = (0.0, 5.0)  # exclusive lower bound, inclusive upper: 0% to 500% annualised
UNDERLYING_VS_HISTORY_WARN_PCT = 20.0


@dataclass(frozen=True)
class Issue:
    kind: str
    severity: str  # "drop" | "reject" | "warn"
    count: int = 1
    detail: str = ""


@dataclass(frozen=True)
class QualityResult:
    snapshot: Optional[MarketSnapshot]  # None when the snapshot was rejected
    issues: tuple[Issue, ...]

    @property
    def rejected(self) -> bool:
        return self.snapshot is None


def _finite(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def quote_fingerprint(snap: MarketSnapshot) -> str:
    """Hash of the visible prices, used to notice a feed that has stopped changing."""
    h = hashlib.sha256()
    h.update(f"{snap.underlying:.6f}".encode())
    for r in snap.rows:
        h.update(f"{r.contract.occ_symbol}|{r.bid:.4f}|{r.ask:.4f}".encode())
    return h.hexdigest()


def check_snapshot(snap: MarketSnapshot, now: datetime, max_age_s: int = MAX_SNAPSHOT_AGE_S) -> QualityResult:
    issues: list[Issue] = []

    def reject(kind: str, detail: str) -> QualityResult:
        return QualityResult(None, tuple(issues) + (Issue(kind, "reject", 1, detail),))

    if not _finite(snap.underlying) or snap.underlying <= 0:
        return reject("BAD_UNDERLYING", f"underlying={snap.underlying!r}")
    if any((not _finite(c)) or c <= 0 for c in snap.closes):
        return reject("BAD_HISTORY", "non-finite or non-positive close in price history")
    age = (now - snap.as_of).total_seconds()
    if age < -MAX_FUTURE_SKEW_S:
        return reject("FUTURE_TIMESTAMP", f"snapshot is {-age:.0f}s ahead of the clock")
    if age > max_age_s:
        return reject("STALE_SNAPSHOT", f"snapshot is {age:.0f}s old (limit {max_age_s}s)")

    kept: list[ChainRow] = []
    changed = False  # True if any row was dropped or had a side value removed
    seen = set()
    counts: dict[str, int] = {}
    for r in snap.rows:
        kind = None
        if not (_finite(r.bid) and _finite(r.ask)) or r.bid < 0 or r.ask < 0:
            kind = "NONFINITE_QUOTE"
        elif r.ask <= 0:
            kind = "ZERO_ASK"
        elif r.bid > r.ask:
            kind = "CROSSED_QUOTE"
        elif r.contract.expiry < snap.as_of.date():
            kind = "EXPIRED_CONTRACT"
        elif r.contract in seen:
            kind = "DUPLICATE_CONTRACT"
        if kind:
            counts[kind] = counts.get(kind, 0) + 1
            changed = True
            continue
        seen.add(r.contract)
        # Implausible side data is removed, not corrected: a missing value is "unknown", which fails closed.
        iv, vol, oi = r.iv, r.volume, r.open_interest
        if iv is not None and not (_finite(iv) and IV_RANGE[0] < iv <= IV_RANGE[1]):
            iv = None
            counts["IMPLAUSIBLE_IV"] = counts.get("IMPLAUSIBLE_IV", 0) + 1
        if vol is not None and (not _finite(vol) or vol < 0):
            vol = None
            counts["NEGATIVE_VOLUME"] = counts.get("NEGATIVE_VOLUME", 0) + 1
        if oi is not None and (not _finite(oi) or oi < 0):
            oi = None
            counts["NEGATIVE_OPEN_INTEREST"] = counts.get("NEGATIVE_OPEN_INTEREST", 0) + 1
        if (iv, vol, oi) != (r.iv, r.volume, r.open_interest):
            changed = True
            r = replace(r, iv=iv, volume=vol, open_interest=oi)
        kept.append(r)
    for kind, n in sorted(counts.items()):
        severity = "drop" if kind in {"NONFINITE_QUOTE", "ZERO_ASK", "CROSSED_QUOTE", "EXPIRED_CONTRACT", "DUPLICATE_CONTRACT"} else "warn"
        issues.append(Issue(kind, severity, n))

    if not kept:
        return reject("EMPTY_CHAIN", f"no usable option rows (started with {len(snap.rows)})")
    if snap.closes:
        gap = abs(snap.underlying - snap.closes[-1]) / snap.closes[-1] * 100
        if gap > UNDERLYING_VS_HISTORY_WARN_PCT:
            issues.append(Issue("UNDERLYING_GAP", "warn", 1, f"spot differs from last close by {gap:.1f}%"))
    return QualityResult(replace(snap, rows=tuple(kept)) if changed else snap, tuple(issues))


def frozen_issue(unchanged_cycles: int, market_open: bool, threshold: int = 3) -> Optional[Issue]:
    """A liquid chain whose every quote is identical for several cycles while the market is open is suspect."""
    if market_open and unchanged_cycles >= threshold:
        return Issue("FROZEN_QUOTES", "warn", unchanged_cycles, f"identical for {unchanged_cycles} cycles")
    return None


__all__ = ["Issue", "QualityResult", "check_snapshot", "quote_fingerprint", "frozen_issue"]
