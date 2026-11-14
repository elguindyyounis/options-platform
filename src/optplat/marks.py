"""One rule for marking an open position, shared by every place that reports unrealized P&L.

A mark is the bid, but only a bid that could plausibly be sold into: a valid quote, not older than
``MAX_MARK_AGE_S``, and with a spread no wider than ``MAX_MARK_SPREAD_PCT`` of the ask. Anything else is
unobservable (mark ``None``), never a guess. The limits mirror the owner's alerter repo, which refuses to mark on a
quote over 30 minutes old or a spread over 35%. Display only: nothing here changes what is traded.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from .models import Quote

MAX_MARK_AGE_S = 1800.0
MAX_FUTURE_SKEW_S = 120.0
MAX_MARK_SPREAD_PCT = 35.0


def mark_from_quote(q: Quote, now: Optional[datetime] = None) -> tuple[Optional[float], str]:
    """Return ``(mark, quality)``. Quality is BID, UNOBSERVABLE, WIDE_SPREAD or STALE."""
    if not q.is_valid() or q.bid <= 0:
        return None, "UNOBSERVABLE"
    now = now or datetime.now(timezone.utc)
    try:
        age = q.age_seconds(now)
    except TypeError:  # naive timestamp: cannot be trusted
        return None, "STALE"
    if not -MAX_FUTURE_SKEW_S <= age <= MAX_MARK_AGE_S:
        return None, "STALE"
    if q.spread_pct_of_ask() > MAX_MARK_SPREAD_PCT:
        return None, "WIDE_SPREAD"
    return q.bid, "BID"
