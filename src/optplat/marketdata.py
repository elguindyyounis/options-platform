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


def snapshot_to_dict(snap: MarketSnapshot) -> dict[str, Any]:
    """JSON-safe form of a snapshot, for the recorder and for replay."""
    return {
        "symbol": snap.symbol,
        "underlying": snap.underlying,
        "closes": list(snap.closes),
        "as_of": snap.as_of.isoformat(),
        "source": snap.source,
        "timestamp_verified": snap.timestamp_verified,
        "fictional": snap.fictional,
        "rows": [
            {
                "contract": r.contract.to_dict(),
                "bid": r.bid,
                "ask": r.ask,
                "volume": r.volume,
                "open_interest": r.open_interest,
                "iv": r.iv,
            }
            for r in snap.rows
        ],
    }


def snapshot_from_dict(d: dict[str, Any]) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=d["symbol"],
        underlying=float(d["underlying"]),
        closes=tuple(float(c) for c in d["closes"]),
        rows=tuple(
            ChainRow(
                OptionContract.from_dict(r["contract"]),
                float(r["bid"]),
                float(r["ask"]),
                r.get("volume"),
                r.get("open_interest"),
                r.get("iv"),
            )
            for r in d["rows"]
        ),
        as_of=datetime.fromisoformat(d["as_of"]),
        source=d["source"],
        timestamp_verified=bool(d["timestamp_verified"]),
        fictional=bool(d.get("fictional", False)),
    )


@dataclass(frozen=True)
class Bar:
    """One daily bar: enough to rank names by activity. Volume is shares, close is the unadjusted last price."""
    day: date
    close: float
    volume: float


class MarketDataProvider(ABC):
    name: str = "abstract"
    fictional: bool = False

    @abstractmethod
    def snapshot(self, symbol: str) -> MarketSnapshot:
        """Underlying history plus an option chain sample. Raise on failure; never fabricate."""

    @abstractmethod
    def quotes_for(self, contracts: Sequence[OptionContract]) -> list[Quote]:
        """Current quotes for specific contracts (used to keep held positions marked)."""

    def daily_bars(self, symbols: Sequence[str]) -> dict[str, list[Bar]]:
        """About two months of daily bars per symbol, for activity ranking. Optional: raise if unsupported."""
        raise NotImplementedError(f"{self.name} cannot supply daily bars")


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

    def daily_bars(self, symbols: Sequence[str]) -> dict[str, list[Bar]]:
        """Fictional bars with made-up volume, for exercising the scanner. Deterministic per symbol."""
        today = self._clock().date()
        days: list[date] = []
        d = today
        while len(days) < 30:
            if d.weekday() < 5:
                days.append(d)
            d -= timedelta(days=1)
        days.reverse()
        out: dict[str, list[Bar]] = {}
        for sym in symbols:
            rng = random.Random(f"{self._seed}:{sym}:bars")
            price = 50.0 + (sum(map(ord, sym)) % 450)
            base = 1_000_000 * (1 + sum(map(ord, sym)) % 40)
            bars = []
            for i, day in enumerate(days):
                price *= math.exp(0.012 * rng.gauss(0, 1))
                surge = 3.0 if (i == len(days) - 1 and sum(map(ord, sym)) % 7 == 0) else 1.0
                bars.append(Bar(day, round(price, 2), round(base * surge * (0.7 + 0.6 * rng.random()))))
            out[sym] = bars
        return out

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

    def daily_bars(self, symbols: Sequence[str]) -> dict[str, list[Bar]]:
        import yfinance as yf

        frame = yf.download(list(symbols), period="2mo", interval="1d", group_by="ticker", auto_adjust=False,
                            progress=False, threads=True)
        out: dict[str, list[Bar]] = {}
        for sym in symbols:
            try:
                sub = frame[sym] if len(symbols) > 1 else frame
                bars = []
                for ts, close, vol in zip(sub.index, sub["Close"].tolist(), sub["Volume"].tolist()):
                    c, v = _num(close), _num(vol)
                    if c and c > 0 and v is not None and v >= 0:
                        bars.append(Bar(ts.date(), c, v))
                if bars:
                    out[sym] = bars
            except Exception:  # noqa: BLE001 - one symbol failing must not hide the others
                continue
        if not out:
            raise RuntimeError("Yahoo returned no usable daily bars")
        return out

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
