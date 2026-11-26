"""Scheduled earnings, FOMC decisions and selected US economic releases.

Unknown never means safe. A calendar answers with a list (possibly empty: "confirmed none") or with None
("could not find out"). The events agent treats None for a single stock as a veto.

Sources, and what is NOT verified:
* FOMC decision days: the Federal Reserve's published calendar, https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm,
  read on 2026-11-11. 2027 dates are marked tentative by the Fed ("tentative until confirmed at the meeting immediately
  preceding it"). A date after 2027 is unknown here, so the macro answer is None. Add a year only from that page.
* Earnings dates: no official free feed exists. `yahoo_earnings_dates` uses Yahoo's unofficial calendar through yfinance;
  those dates are often estimates and the call has not been verified against the live service from this environment.
BLS coverage for CPI and the Employment Situation is limited to November–December 2026.
Other macro releases, dividends, index rebalances and company-specific news are outside this calendar.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from .models import utcnow

FOMC_SOURCE = "federalreserve.gov FOMC calendar, read 2026-11-11"
# Decision day = the last day of each two-day meeting.
FOMC_DECISION_DAYS: dict[int, tuple[date, ...]] = {
    2026: tuple(date(2026, m, d) for m, d in ((1, 28), (3, 18), (4, 29), (6, 17), (7, 29), (9, 16), (10, 28), (12, 9))),
    2027: tuple(date(2027, m, d) for m, d in ((1, 27), (3, 17), (4, 28), (6, 9), (7, 28), (9, 15), (10, 27), (12, 8))),
}
TENTATIVE_YEARS = frozenset({2027})
BLS_SOURCE = "https://www.bls.gov/schedule/2026/home.htm"
BLS_START, BLS_END = date(2026, 11, 1), date(2026, 12, 31)
BLS_RELEASES = (
    (date(2026, 11, 6), "US jobs"),
    (date(2026, 11, 10), "US CPI"),
    (date(2026, 12, 4), "US jobs"),
    (date(2026, 12, 10), "US CPI"),
)

# Funds have no earnings. Anything not listed here is treated as a single stock whose earnings date must be known.
ETFS = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "VOO", "IVV", "VTI", "EFA", "EEM", "TLT", "HYG", "LQD", "GLD", "SLV", "USO", "SMH", "XBI",
    "XLF", "XLE", "XLK", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC",
})


@dataclass(frozen=True)
class Event:
    kind: str
    day: date
    source: str
    tentative: bool = False

    def to_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "day": self.day.isoformat(), "source": self.source, "tentative": self.tentative}


@dataclass(frozen=True)
class EventView:
    """What the committee is told about one candidate. None means unknown, which is not the same as empty."""
    macro: Optional[tuple[Event, ...]]
    earnings: Optional[tuple[Event, ...]]
    is_etf: bool
    economic_releases: tuple[Event, ...] = ()
    economic_window_covered: bool = False


EarningsSource = Callable[[str], Optional[list[date]]]


def earnings_source_for(data: str, fallback: str = "yahoo") -> Optional[EarningsSource]:
    """Where earnings dates come from. IBKR's shared service has none, so with ``OPTPLAT_DATA=ibkr`` they come from
    Yahoo unless the Yahoo fallback is off (owner decision 2026-11-27: Yahoo only where IBKR has no data). Without a
    source every single-stock earnings check is unknown, and unknown blocks swing and option-lane entries."""
    if data == "yahoo" or (data == "ibkr" and fallback == "yahoo"):
        return yahoo_earnings_dates
    return None


class EventCalendar:
    CACHE_TTL = timedelta(hours=12)

    def __init__(self, earnings_source: Optional[EarningsSource] = None, clock: Callable[[], datetime] = utcnow) -> None:
        self._source = earnings_source
        self._clock = clock
        self._cache: dict[str, tuple[datetime, Optional[list[date]]]] = {}

    def macro(self, start: date, end: date) -> Optional[list[Event]]:
        years = range(start.year, end.year + 1)
        if any(y not in FOMC_DECISION_DAYS for y in years):
            return None  # the table does not cover these dates: unknown, not "no events"
        return [Event("FOMC", d, FOMC_SOURCE, d.year in TENTATIVE_YEARS)
                for y in years for d in FOMC_DECISION_DAYS[y] if start <= d <= end]

    def earnings(self, symbol: str, start: date, end: date) -> Optional[list[Event]]:
        if symbol.upper() in ETFS:
            return []
        if self._source is None:
            return None
        now = self._clock()
        hit = self._cache.get(symbol)
        if hit is None or now - hit[0] > self.CACHE_TTL:
            try:
                dates = self._source(symbol)
            except Exception:  # noqa: BLE001
                dates = None
            self._cache[symbol] = (now, dates)
            hit = self._cache[symbol]
        if hit[1] is None:
            return None
        return [Event("EARNINGS", d, "earnings source (unofficial, often an estimate)", True) for d in sorted(hit[1]) if start <= d <= end]

    def view(self, symbol: str, start: date, end: date) -> EventView:
        try:
            macro = self.macro(start, end)
            earnings = self.earnings(symbol, start, end)
        except Exception:  # noqa: BLE001
            macro = earnings = None
        economic = tuple(Event(kind, day, BLS_SOURCE) for day, kind in BLS_RELEASES if start <= day <= end)
        near_end = min(end, start + timedelta(days=1))
        return EventView(None if macro is None else tuple(macro), None if earnings is None else tuple(earnings),
                         symbol.upper() in ETFS, economic, BLS_START <= start <= near_end <= BLS_END)


def yahoo_earnings_dates(symbol: str) -> Optional[list[date]]:
    """Upcoming earnings dates from Yahoo's unofficial calendar. An empty or failed answer is None (unknown):
    Yahoo cannot tell us "no earnings scheduled" apart from "not published yet"."""
    try:
        import yfinance as yf  # optional dependency, same as the Yahoo data provider

        raw = yf.Ticker(symbol).calendar
        values = raw.get("Earnings Date") if isinstance(raw, dict) else None
        out = [v.date() if isinstance(v, datetime) else v for v in (values or []) if isinstance(v, (date, datetime))]
        return out or None
    except Exception:  # noqa: BLE001
        return None
