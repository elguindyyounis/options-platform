"""Market-data providers.

* ``DemoDataProvider``   - FICTIONAL, deterministic prices so the whole pipeline can run offline.
* ``StaticDataProvider`` - hand-set snapshots, for tests.
* ``YahooDataProvider``  - unofficial, delayed, research-only. Its quote times are never verified.
"""
from __future__ import annotations

import math
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable, Optional, Sequence

from .models import OptionContract, Quote, Right, utcnow


@dataclass(frozen=True)
class ChainRow:
    contract: OptionContract
    bid: float
    ask: float
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    iv: Optional[float] = None

    def to_quote(self, as_of: datetime, source: str, verified: bool) -> Quote:
        return Quote(self.contract, self.bid, self.ask, as_of, source, timestamp_verified=verified)


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    underlying: float
    closes: tuple[float, ...]
    rows: tuple[ChainRow, ...]
    as_of: datetime
    source: str
    timestamp_verified: bool
    fictional: bool = False


class MarketDataProvider(ABC):
    name: str = "abstract"
    fictional: bool = False

    @abstractmethod
    def snapshot(self, symbol: str) -> MarketSnapshot:
        """Underlying history plus an option chain sample. Raise on failure; never fabricate."""

    @abstractmethod
    def quotes_for(self, contracts: Sequence[OptionContract]) -> list[Quote]:
        """Current quotes for specific contracts (used to keep held positions marked)."""


# ---------------------------------------------------------------- Black-Scholes (demo only)
def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(spot: float, strike: float, t_years: float, vol: float, rate: float, right: Right) -> float:
    if t_years <= 0:
        return max(0.0, spot - strike) if right is Right.CALL else max(0.0, strike - spot)
    sqrt_t = math.sqrt(t_years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * vol * vol) * t_years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    call = spot * _ncdf(d1) - strike * math.exp(-rate * t_years) * _ncdf(d2)
    if right is Right.CALL:
        return call
    return call - spot + strike * math.exp(-rate * t_years)


class DemoDataProvider(MarketDataProvider):
    """Synthetic market. The numbers are made up: use it to exercise the system, never to judge it."""

    name = "demo-synthetic"
    fictional = True

    def __init__(
        self,
        *,
        seed: int = 7,
        clock: Callable[[], datetime] = utcnow,
        vol: float = 0.30,
        rate: float = 0.04,
        bias: Optional[dict[str, float]] = None,
    ) -> None:
        self._seed = seed
        self._clock = clock
        self._vol = vol
        self._rate = rate
        self._bias = dict(bias if bias is not None else {"SPY": 0.004, "QQQ": -0.004})
        self._anchor = clock().date()
        self._rng = random.Random(seed)
        self._state: dict[str, list[float]] = {}

    def _closes(self, symbol: str) -> list[float]:
        if symbol not in self._state:
            rng = random.Random(f"{self._seed}:{symbol}")
            price = 50.0 + (sum(map(ord, symbol)) % 450)
            bias = self._bias.get(symbol, 0.0)
            closes: list[float] = []
            for _ in range(80):
                price *= math.exp(bias + 0.01 * rng.gauss(0, 1))
                closes.append(round(price, 2))
            self._state[symbol] = closes
        return self._state[symbol]

    def advance(self) -> None:
        """Move every known underlying one random step (call once per engine cycle)."""
        for closes in self._state.values():
            closes.append(round(closes[-1] * math.exp(0.012 * self._rng.gauss(0, 1)), 2))
            del closes[:-120]

    def _expiries(self) -> list[date]:
        out = []
        for days in (21, 42, 70, 105):
            d = self._anchor + timedelta(days=days)
            out.append(d + timedelta(days=(4 - d.weekday()) % 7))  # next Friday
        return out

    def _row(self, symbol: str, spot: float, expiry: date, right: Right, strike: float) -> Optional[ChainRow]:
        dte = (expiry - self._clock().date()).days
        if dte < 0 or strike <= 0:
            return None
        mid = max(0.05, bs_price(spot, strike, dte / 365, self._vol, self._rate, right))
        half = max(0.01, 0.03 * mid)
        bid = max(0.01, round(mid - half, 2))
        ask = round(mid + half, 2)
        m = abs(strike / spot - 1)
        volume = int(1500 * math.exp(-((m / 0.04) ** 2))) + 5
        oi = int(4000 * math.exp(-((m / 0.06) ** 2))) + 120
        return ChainRow(OptionContract(symbol, expiry, right, strike), bid, ask, volume, oi, self._vol)

    def snapshot(self, symbol: str) -> MarketSnapshot:
        closes = self._closes(symbol)
        spot = closes[-1]
        now = self._clock()
        step = 5.0 if spot > 100 else 1.0
        base = round(spot / step) * step
        rows: list[ChainRow] = []
        for expiry in self._expiries():
            if (expiry - now.date()).days < 7:
                continue
            for k in range(-6, 7):
                for right in (Right.CALL, Right.PUT):
                    row = self._row(symbol, spot, expiry, right, base + k * step)
                    if row:
                        rows.append(row)
        return MarketSnapshot(symbol, spot, tuple(closes), tuple(rows), now, self.name, True, True)

    def quotes_for(self, contracts: Sequence[OptionContract]) -> list[Quote]:
        now = self._clock()
        out = []
        for c in contracts:
            spot = self._closes(c.underlying)[-1]
            row = self._row(c.underlying, spot, c.expiry, c.right, c.strike)
            if row:
                out.append(row.to_quote(now, self.name, True))
        return out


class StaticDataProvider(MarketDataProvider):
    """Returns whatever snapshots you set. Quote times follow the injected clock."""

    name = "static-test"

    def __init__(self, clock: Callable[[], datetime] = utcnow) -> None:
        self._clock = clock
        self._snaps: dict[str, MarketSnapshot] = {}

    def set_snapshot(self, snap: MarketSnapshot) -> None:
        self._snaps[snap.symbol] = snap

    def snapshot(self, symbol: str) -> MarketSnapshot:
        if symbol not in self._snaps:
            raise RuntimeError(f"No static snapshot for {symbol}")
        return replace(self._snaps[symbol], as_of=self._clock())

    def quotes_for(self, contracts: Sequence[OptionContract]) -> list[Quote]:
        now = self._clock()
        wanted = set(contracts)
        return [
            r.to_quote(now, self.name, s.timestamp_verified)
            for s in self._snaps.values()
            for r in s.rows
            if r.contract in wanted
        ]


# ---------------------------------------------------------------- Yahoo (unofficial)
def _num(value: Any) -> Optional[float]:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def rows_from_records(records: Iterable[dict[str, Any]], symbol: str, expiry: date, right: Right) -> list[ChainRow]:
    """Map raw chain records (e.g. DataFrame.to_dict('records')) to rows. Bad rows are dropped, not repaired."""
    rows: list[ChainRow] = []
    for r in records:
        strike, bid, ask = _num(r.get("strike")), _num(r.get("bid")), _num(r.get("ask"))
        if strike is None or strike <= 0 or bid is None or ask is None or ask <= 0 or bid < 0 or bid > ask:
            continue
        volume, oi, iv = _num(r.get("volume")), _num(r.get("openInterest")), _num(r.get("impliedVolatility"))
        if iv is not None and not 0 < iv < 10:
            iv = None
        rows.append(
            ChainRow(
                OptionContract(symbol, expiry, right, strike),
                bid,
                ask,
                int(volume) if volume is not None else None,
                int(oi) if oi is not None else None,
                iv,
            )
        )
    return rows


class YahooDataProvider(MarketDataProvider):
    """Unofficial and delayed. Quote times are NOT verified, so the default risk policy rejects them."""

    name = "yahoo-unofficial"

    def __init__(self, *, max_expiries: int = 4, clock: Callable[[], datetime] = utcnow) -> None:
        self._max = max_expiries
        self._clock = clock

    def _chain_rows(self, ticker: Any, symbol: str, expiry: date) -> list[ChainRow]:
        chain = ticker.option_chain(expiry.isoformat())
        return rows_from_records(chain.calls.to_dict("records"), symbol, expiry, Right.CALL) + rows_from_records(
            chain.puts.to_dict("records"), symbol, expiry, Right.PUT
        )

    def snapshot(self, symbol: str) -> MarketSnapshot:
        import yfinance as yf  # optional dependency: pip install -e ".[yahoo]"

        ticker = yf.Ticker(symbol)
        history = ticker.history(period="6mo", interval="1d", auto_adjust=True)
        closes = [v for v in (_num(x) for x in history["Close"].tolist()) if v and v > 0]
        if len(closes) < 5:
            raise RuntimeError("No usable underlying price history")
        today = self._clock().date()
        expiries = []
        for e in ticker.options or []:
            d = date.fromisoformat(e)
            if 14 <= (d - today).days <= 180:
                expiries.append(d)
        rows: list[ChainRow] = []
        for d in expiries[: self._max]:
            rows.extend(self._chain_rows(ticker, symbol, d))
        return MarketSnapshot(symbol, closes[-1], tuple(closes[-120:]), tuple(rows), self._clock(), self.name, False)

    def quotes_for(self, contracts: Sequence[OptionContract]) -> list[Quote]:
        import yfinance as yf

        now = self._clock()
        wanted = set(contracts)
        out: list[Quote] = []
        for symbol, expiry in sorted({(c.underlying, c.expiry) for c in contracts}):
            for row in self._chain_rows(yf.Ticker(symbol), symbol, expiry):
                if row.contract in wanted:
                    out.append(row.to_quote(now, self.name, False))
        return out
