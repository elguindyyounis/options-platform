"""Read-only consumer of the shared, authenticated localhost IBKR data service.

The service is maintained in options-alerter/ibkr_marketdata.py. No ib_async
dependency, TWS socket, credentials or order methods exist in this consumer.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Optional, Sequence
import math
import sys
import threading
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from .marketdata import Bar, ChainRow, IntradayBar, MarketDataProvider, MarketSnapshot
from .market_clock import NY
from .models import OptionContract, Quote, Right

DAILY_BUDGET = 15          # new daily-bar fetches per window: leaves most of the shared budget to the Alerter
DAILY_WINDOW_S = 600
DAILY_TTL_S = 6 * 3600
VERIFIED_MAX_AGE_S = 5.0   # the service's own limit for its cross-checked bid/ask
VERIFIED_SOURCE = 'ibkr-paper-verified'
TOKEN_PATH = Path.home() / 'Library/Application Support/OptionsMarketData/token'


class ServiceError(RuntimeError):
    """The shared service refused a request. Its text is the HTTP status and the service's own fixed reason string."""


def service_error(exc: HTTPError) -> ServiceError:
    reason = ''
    try:
        body = json.loads(exc.read(2000) or b'{}')
        reason = str(body.get('reason') or body.get('error') or '')
    except Exception:  # noqa: BLE001 - an unreadable body still reports its status
        pass
    reason = ''.join(ch for ch in reason[:80] if ch.isprintable())
    return ServiceError(f'HTTP {exc.code}' + (f' {reason}' if reason else ''))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise RuntimeError('Local market-data redirects forbidden')


def request(resource: str, params=None, *, timeout=80):
    if resource not in ('health', 'snapshot', 'history', 'quotes', 'execution-quote'):
        raise ValueError('Unknown read-only resource')
    token = TOKEN_PATH.read_text().strip()
    if len(token) < 32 or TOKEN_PATH.stat().st_mode & 0o077:
        raise RuntimeError('Private market-data token unavailable')
    url = 'http://127.0.0.1:8791/v1/'+resource
    if params:
        url += '?'+urlencode(params)
    req = Request(url, headers={'Authorization': 'Bearer '+token})
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=timeout) as response:
            raw = response.read(4000001)
    except HTTPError as exc:
        # Without the status and reason every refusal read as a bare "HTTPError" and could not be diagnosed.
        raise service_error(exc) from None
    if len(raw) > 4000000:
        raise RuntimeError('Market-data response exceeds limit')
    return json.loads(raw)


USAGE_WINDOW_S = 600       # the service's historical budget window (30 bar requests per 10 minutes, all consumers)
_KIND = {'snapshot': 'chain', 'execution-quote': 'verify', 'quotes': 'quotes'}
_BUDGETED = ('chain', 'bars_daily', 'bars_5min')  # each can spend one historical request at the service on a cache miss
_SKIP = ('optplat.ibkr_data', 'optplat.fallback_data')


def _caller() -> str:
    """The platform module that asked (engine, scanner, optionlanes, ...), found by walking up the stack."""
    f = sys._getframe(2)
    while f is not None:
        mod = f.f_globals.get('__name__', '')
        if mod.startswith('optplat.') and mod not in _SKIP:
            return mod.split('.', 1)[1]
        f = f.f_back
    return 'other'


class IBKRDataProvider(MarketDataProvider):
    name = 'ibkr-shared-research-only'
    # Experimental lanes must honor this independently of the main risk policy.
    execution_veto = True

    def __init__(self, transport=request, clock=lambda: datetime.now(timezone.utc)):
        self._request = transport
        self._clock = clock
        self._daily: dict[str, tuple[date, datetime, list[Bar]]] = {}
        self._fetches: deque[datetime] = deque()
        self._usage: deque[tuple[datetime, str, str, str]] = deque(maxlen=5000)  # (at, kind, caller, outcome)
        self._usage_lock = threading.Lock()

    def _call(self, resource: str, params=None, **kw):
        """Every service request goes through here so the platform can see what it spends (display only)."""
        kind = _KIND.get(resource) or ('bars_5min' if (params or {}).get('interval') == '5 mins' else 'bars_daily')
        caller, outcome = _caller(), 'ok'
        try:
            return self._request(resource, params, **kw)
        except Exception as exc:  # noqa: BLE001 - recorded, then raised unchanged
            outcome = str(exc)[:80] if isinstance(exc, ServiceError) else type(exc).__name__
            raise
        finally:
            with self._usage_lock:
                self._usage.append((self._clock(), kind, caller, outcome))

    def usage(self) -> dict:
        """What this platform asked the shared service for in the last 10 minutes, by caller and kind.

        Counts requests SENT. The service answers some from its own cache at no cost, so the budgeted total is an upper
        bound on what the platform spent of the 30 bar requests per 10 minutes all consumers share."""
        now = self._clock()
        with self._usage_lock:
            rows = [u for u in self._usage if (now - u[0]).total_seconds() <= USAGE_WINDOW_S]
        by_caller: dict[str, dict[str, int]] = {}
        refused: dict[str, int] = {}
        for _at, kind, caller, outcome in rows:
            c = by_caller.setdefault(caller, {})
            c[kind] = c.get(kind, 0) + 1
            if outcome != 'ok':
                refused[outcome] = refused.get(outcome, 0) + 1
        return {'window_s': USAGE_WINDOW_S, 'sent': len(rows),
                'budgeted_sent': sum(1 for u in rows if u[1] in _BUDGETED),
                'by_caller': by_caller, 'refused': refused,
                'note': 'requests sent by this platform; cache hits at the service cost nothing, so this is an upper bound'}

    def health(self):
        try:
            return self._request('health', timeout=.75)
        except Exception:
            return {'state': 'UNAVAILABLE', 'connected': False, 'execution_eligible': False}

    def snapshot(self, symbol: str) -> MarketSnapshot:
        return self.snapshot_window(symbol, 7, 730, 4)

    def snapshot_window(self, symbol: str, min_dte: int, max_dte: int, max_expiries: int = 4) -> MarketSnapshot:
        raw = self._call('snapshot', {'symbol': symbol, 'min_dte': min_dte,
                                        'max_dte': max_dte, 'max_expiries': min(4, max_expiries)})
        rows = []
        times = []
        for r in raw['rows']:
            bid, ask = r.get('bid'), r.get('ask')
            # Stale, delayed, frozen and missing quotes do not enter this snapshot.
            if r.get('status') != 'LIVE_UNVERIFIED' or not r.get('received_at'):
                continue
            if bid is None or ask is None or not 0 < bid <= ask:
                continue
            times.append(datetime.fromisoformat(r['received_at']))
            rows.append(ChainRow(OptionContract(symbol, date.fromisoformat(r['expiry']), Right(r['right']),
                                               r['strike'], r['multiplier']), bid, ask,
                                 r.get('volume'), r.get('open_interest'), r.get('iv'), r.get('last')))
        # A response clock cannot launder an old BBO into a new observation.
        as_of = min(times) if times else datetime.fromisoformat(raw['as_of'])
        return MarketSnapshot(symbol, raw['underlying'], tuple(b['close'] for b in raw['bars']),
                              tuple(rows), as_of, self.name, False)

    @staticmethod
    def _contract_json(c: OptionContract) -> dict:
        return {'symbol': c.underlying, 'expiry': c.expiry.isoformat(), 'right': c.right.value,
                'strike': c.strike, 'multiplier': c.multiplier}

    @staticmethod
    def _same(row: dict, c: OptionContract) -> bool:
        return (row.get('symbol') == c.underlying and row.get('expiry') == c.expiry.isoformat()
                and row.get('right') == c.right.value and row.get('strike') == c.strike
                and row.get('multiplier', 100) == c.multiplier)

    def execution_quote(self, contract: OptionContract) -> Optional[Quote]:
        """The service's cross-check of ONE contract: its live bid/ask must match IBKR's own timestamped BID_ASK record
        within 5 seconds. Returns a verified quote dated at that IBKR event time, or None for any doubt.

        This is the only path by which IBKR data can satisfy the risk policy's verified-time rule. It spends the shared
        historical budget, so the engine calls it only for an order it is about to send.
        """
        try:
            row = self._call('execution-quote', {'contract': json.dumps(self._contract_json(contract))}, timeout=30)
            now = self._clock()
            at = datetime.fromisoformat(row['source_quote_at'])
            seen = datetime.fromisoformat(row['received_at'])
            bid, ask = float(row['bid']), float(row['ask'])
        except Exception:  # noqa: BLE001 - unavailable, malformed or refused: not verified
            return None
        if (row.get('status') != 'PAPER_VERIFIED' or row.get('execution_eligible') is not True
                or row.get('market_data_type') != 1 or not self._same(row, contract)
                or at.tzinfo is None or seen.tzinfo is None
                or any(not -1.0 <= (now - t).total_seconds() <= VERIFIED_MAX_AGE_S for t in (at, seen))
                or not (math.isfinite(bid) and math.isfinite(ask)) or bid < 0 or ask <= 0 or bid > ask):
            return None
        return Quote(contract, bid, ask, at, VERIFIED_SOURCE, timestamp_verified=True)

    def decision_quotes_for(self, contracts: Sequence[OptionContract]) -> list[Quote]:
        """Live but UNVERIFIED IBKR quotes for the main account's held contracts, so exits can be noticed.

        The risk policy refuses any order on an unverified IBKR quote, so these can trigger an exit decision but never
        fill one: the engine fetches a verified quote before it sends the exit. Experimental lanes do not use this.
        """
        out: list[Quote] = []
        for i in range(0, len(contracts), 24):
            batch = list(contracts[i:i + 24])
            raw = self._call('quotes', {'contracts': json.dumps([self._contract_json(c) for c in batch])})
            for c in batch:
                row = next((r for r in raw.get('rows', []) if self._same(r, c)), None)
                if (not row or row.get('status') != 'LIVE_UNVERIFIED' or row.get('market_data_type') != 1
                        or not row.get('received_at') or row.get('bid') is None or row.get('ask') is None):
                    continue
                bid, ask = float(row['bid']), float(row['ask'])
                if math.isfinite(bid) and math.isfinite(ask) and 0 <= bid <= ask and ask > 0:
                    out.append(Quote(c, bid, ask, datetime.fromisoformat(row['received_at']), 'ibkr',
                                     timestamp_verified=False))
        return out

    def quotes_for(self, contracts: Sequence[OptionContract]) -> list[Quote]:
        # Executable marks are deliberately withheld until venue BBO time is verified.
        # Both the main broker and experimental lane ledgers consume this method.
        return []

    def daily_bars(self, symbols: Sequence[str], months: int = 2) -> dict[str, list[Bar]]:
        """Daily stock bars for the symbols the shared budget allows; the rest are left out (no data, no entry).

        The service allows about 55 history requests per 10 minutes for every consumer together, and the scan
        universe is about 200 names, so this consumer caches each name's bars for DAILY_TTL_S (never past the New York
        day they were fetched) and starts at most DAILY_BUDGET new fetches per DAILY_WINDOW_S. One name failing does
        not fail the others. Index symbols such as ^VIX are not served by the service and are left out unasked.
        """
        now = self._clock()
        today = now.astimezone(NY).date()
        while self._fetches and now - self._fetches[0] > timedelta(seconds=DAILY_WINDOW_S):
            self._fetches.popleft()
        out: dict[str, list[Bar]] = {}
        for s in symbols:
            if not s or not s[0].isalpha():
                continue
            hit = self._daily.get(s)
            if hit and hit[0] == today and now - hit[1] <= timedelta(seconds=DAILY_TTL_S):
                out[s] = hit[2]
                continue
            if len(self._fetches) >= DAILY_BUDGET:
                continue
            self._fetches.append(now)
            try:
                bars = [Bar(date.fromisoformat(b['timestamp'][:10]), b['close'], b['volume'])
                        for b in self._call('history', {'symbol': s})['bars']]
            except Exception:  # noqa: BLE001 - this name is unknown this round; the others still count
                continue
            self._daily[s] = (today, now, bars)
            out[s] = bars
        return out

    def intraday_bars(self, symbol: str) -> list[IntradayBar]:
        raw = self._call('history', {'symbol': symbol, 'interval': '5 mins'})
        return [IntradayBar(datetime.fromisoformat(b['timestamp']).astimezone(timezone.utc),
                            b['open'], b['high'], b['low'], b['close'], b['volume']) for b in raw['bars']]
