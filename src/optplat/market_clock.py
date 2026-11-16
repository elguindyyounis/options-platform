"""Approximate US equity-options session clock. Fails CLOSED for any year it has no calendar for.

This is a hand-maintained table, not an exchange status feed. Unexpected closures, halts and
holiday-schedule changes are not detected.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

HOLIDAYS: dict[int, frozenset[date]] = {
    2026: frozenset(
        {
            date(2026, 1, 1),    # New Year's Day
            date(2026, 1, 19),   # Martin Luther King Jr. Day
            date(2026, 2, 16),   # Presidents' Day
            date(2026, 4, 3),    # Good Friday
            date(2026, 5, 25),   # Memorial Day
            date(2026, 6, 19),   # Juneteenth
            date(2026, 7, 3),    # Independence Day (observed)
            date(2026, 9, 7),    # Labor Day
            date(2026, 11, 26),  # Thanksgiving
            date(2026, 12, 25),  # Christmas
        }
    ),
}
EARLY_CLOSES: dict[int, frozenset[date]] = {
    2026: frozenset({date(2026, 11, 27), date(2026, 12, 24)}),
}

OPEN = time(9, 30)
CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)


def session_status(now: datetime) -> tuple[bool, str]:
    """Return (is_open, human-readable reason). ``now`` must be timezone-aware."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(NY)
    day = local.date()
    if day.year not in HOLIDAYS:
        return False, f"Holiday calendar not loaded for {day.year}; failing closed"
    if day.weekday() >= 5:
        return False, "Weekend"
    if day in HOLIDAYS[day.year]:
        return False, "Market holiday"
    early = day in EARLY_CLOSES.get(day.year, frozenset())
    close = EARLY_CLOSE if early else CLOSE
    t = local.time()
    if t < OPEN:
        return False, "Before the open"
    if t >= close:
        return False, "After the close"
    return True, "Regular session (early close)" if early else "Regular session"


def is_open(now: datetime) -> bool:
    return session_status(now)[0]


def upcoming_closures(now: datetime, days: int = 21) -> list[dict[str, str]]:
    """Known market holidays and early closes in the next ``days`` days, from the table above.

    Display only. Empty when the year has no table (the clock then fails closed anyway), and it
    knows nothing about earnings, Fed or data releases: those need an event source.
    """
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    today = now.astimezone(NY).date()
    out: list[dict[str, str]] = []
    for offset in range(days + 1):
        day = today + timedelta(days=offset)
        if day.year not in HOLIDAYS:
            continue
        if day in HOLIDAYS[day.year]:
            out.append({"date": day.isoformat(), "kind": "closed"})
        elif day in EARLY_CLOSES.get(day.year, frozenset()):
            out.append({"date": day.isoformat(), "kind": "early_close"})
    return out
