"""Read-only consumer of the shared, authenticated localhost IBKR data service.

The service is maintained in options-alerter/ibkr_marketdata.py. No ib_async
dependency, TWS socket, credentials or order methods exist in this consumer.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from typing import Sequence
from urllib.parse import urlencode
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler

from .marketdata import Bar, ChainRow, IntradayBar, MarketDataProvider, MarketSnapshot
from .models import OptionContract, Quote, Right

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

    def __init__(self, transport=request):
        self._request = transport

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
        return {s: [Bar(date.fromisoformat(b['timestamp'][:10]), b['close'], b['volume'])
                    for b in self._request('history', {'symbol': s})['bars']] for s in symbols}

    def intraday_bars(self, symbol: str) -> list[IntradayBar]:
        raw = self._request('history', {'symbol': symbol, 'interval': '5 mins'})
        return [IntradayBar(datetime.fromisoformat(b['timestamp']).astimezone(timezone.utc),
                            b['open'], b['high'], b['low'], b['close'], b['volume']) for b in raw['bars']]
