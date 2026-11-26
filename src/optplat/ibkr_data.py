"""Read-only consumer of the shared, authenticated localhost IBKR data service.

The service is maintained in options-alerter/ibkr_marketdata.py. No ib_async
dependency, TWS socket, credentials or order methods exist in this consumer.
"""
from __future__ import annotations

from collections import deque
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Sequence
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from .marketdata import Bar, ChainRow, IntradayBar, MarketDataProvider, MarketSnapshot
from .market_clock import NY
from .models import OptionContract, Quote, Right

DAILY_BUDGET = 15          # new daily-bar fetches per window: leaves most of the shared budget to the Alerter
DAILY_WINDOW_S = 600
DAILY_TTL_S = 6 * 3600
TOKEN_PATH = Path.home() / 'Library/Application Support/OptionsMarketData/token'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise RuntimeError('Local market-data redirects forbidden')


def request(resource: str, params=None, *, timeout=80):
    if resource not in ('health', 'snapshot', 'history', 'quotes'):
        raise ValueError('Unknown read-only resource')
    token = TOKEN_PATH.read_text().strip()
    if len(token) < 32 or TOKEN_PATH.stat().st_mode & 0o077:
        raise RuntimeError('Private market-data token unavailable')
    url = 'http://127.0.0.1:8791/v1/'+resource
    if params:
        url += '?'+urlencode(params)
    req = Request(url, headers={'Authorization': 'Bearer '+token})
    with build_opener(ProxyHandler({}), NoRedirect()).open(req, timeout=timeout) as response:
        raw = response.read(4000001)
    if len(raw) > 4000000:
        raise RuntimeError('Market-data response exceeds limit')
    return json.loads(raw)


class IBKRDataProvider(MarketDataProvider):
    name = 'ibkr-shared-research-only'
    # Experimental lanes must honor this independently of the main risk policy.
    execution_veto = True

    def __init__(self, transport=request, clock=lambda: datetime.now(timezone.utc)):
        self._request = transport
        self._clock = clock
        self._daily: dict[str, tuple[date, datetime, list[Bar]]] = {}
        self._fetches: deque[datetime] = deque()

    def health(self):
        try:
            return self._request('health', timeout=.75)
        except Exception:
            return {'state': 'UNAVAILABLE', 'connected': False, 'execution_eligible': False}

    def snapshot(self, symbol: str) -> MarketSnapshot:
        return self.snapshot_window(symbol, 7, 730, 4)

    def snapshot_window(self, symbol: str, min_dte: int, max_dte: int, max_expiries: int = 4) -> MarketSnapshot:
        raw = self._request('snapshot', {'symbol': symbol, 'min_dte': min_dte,
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
                        for b in self._request('history', {'symbol': s})['bars']]
            except Exception:  # noqa: BLE001 - this name is unknown this round; the others still count
                continue
            self._daily[s] = (today, now, bars)
            out[s] = bars
        return out

    def intraday_bars(self, symbol: str) -> list[IntradayBar]:
        raw = self._request('history', {'symbol': symbol, 'interval': '5 mins'})
        return [IntradayBar(datetime.fromisoformat(b['timestamp']).astimezone(timezone.utc),
                            b['open'], b['high'], b['low'], b['close'], b['volume']) for b in raw['bars']]
