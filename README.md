# options-platform

A **paper-first** options trading platform MVP: a safety-first execution core (risk gate, order
lifecycle, broker adapter contract, audit trail) plus a simple end-to-end loop (data, baseline
strategy, exits, scheduler, dashboard) so you can watch the whole thing run.

**The baseline strategy has no demonstrated edge.** It exists to exercise the pipeline. The bundled
demo market is fictional random data, so profit or loss there means nothing.

**There is no live-trading code path.** The order manager refuses any broker adapter that is not in
`PAPER` mode, and the API has no live endpoint.

## What is here

| Piece | File | Purpose |
|---|---|---|
| Domain types | `src/optplat/models.py` | Contracts, quotes, orders, order states |
| Risk engine | `src/optplat/risk.py` | Deterministic, fail-closed policy. Nothing can waive it |
| Order manager | `src/optplat/orders.py` | State machine, idempotency, kill switch, reconcile after crashes |
| Broker contract | `src/optplat/broker/base.py` | The interface your broker integration implements |
| Simulated broker | `src/optplat/broker/sim.py` | Conservative fills (ask + slippage), never invents fills |
| IBKR paper skeleton | `src/optplat/broker/ibkr.py` | Paper-only config guards; methods for you to implement |
| Storage | `src/optplat/store.py` | SQLite: orders, append-only audit log, kill switch |
| API | `src/optplat/api.py` | Token-protected local FastAPI app |
| Conformance tests | `tests/conformance.py` | Behaviour every broker adapter must pass |
| Trading engine | `src/optplat/engine.py` | One cycle: reconcile, cancel stale orders, exits, then entries. Plus a background runner |
| Exit rules | `src/optplat/exits.py` | Take profit, stop loss, expiry window, optional time stop. Unpriceable means UNOBSERVABLE |
| Strategy | `src/optplat/strategy.py` | Strategy interface and a baseline liquid-trend strategy |
| Market data | `src/optplat/marketdata.py` | Fictional demo market, static test provider, unofficial Yahoo provider |
| Market clock | `src/optplat/market_clock.py` | NYSE session table; fails closed for years it has no calendar for |
| Dashboard | `src/optplat/static/` | Single page served at `/`: controls, positions, orders, last cycle, results |

## The MVP loop

Each cycle (manual, or every N seconds while the loop is running):

1. Reconcile any order whose outcome is unknown, and cancel resting orders older than the TTL.
2. **Exits first.** Price every open position. Take profit, stop loss, or an approaching expiry sells
   it. A position that cannot be priced is `UNOBSERVABLE`, never a silent hold. The kill switch does
   not block exits.
3. **Entries last, and only if all guards pass.** Automatic entries are **off by default**, cannot be
   enabled without automatic exits, and pause when the market is closed, the kill switch is on, a held
   position cannot be priced, or an order is unresolved. The risk engine still has the final veto.

Safety limits (see `risk.py`): 1% of equity per position, 10% total premium, 15% max spread, quotes
under 60 seconds old with a verified timestamp, 2 contracts per underlying and direction, 12
positions, and a re-entry cooldown after selling a contract.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # 140 tests

export OPTPLAT_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m optplat                        # http://127.0.0.1:8800 (simulated broker)
```

With the simulated broker you seed a quote, then submit an order:

```bash
curl -s -X POST localhost:8800/api/sim/quote -H "X-API-Token: $OPTPLAT_API_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"underlying":"SPY","expiry":"2026-12-18","right":"C","strike":600,"bid":1.90,"ask":2.00}'

curl -s -X POST localhost:8800/api/paper/orders -H "X-API-Token: $OPTPLAT_API_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"idempotency_key":"demo-0001","candidate_id":"demo","underlying":"SPY","expiry":"2026-12-18",
       "right":"C","strike":600,"quantity":4,"limit_price":2.02}'
```

## Design rules

1. Research and execution are separate. This repo only does execution plumbing.
2. The risk engine has the final veto. Missing quote, stale quote, unverified quote time, wide spread,
   oversized order, kill switch, or unexpected data all mean **reject**.
3. A broker call that fails with an unknown outcome is never guessed. The order goes to
   `ERROR_RECONCILE_REQUIRED` and `reconcile()` asks the broker what really happened.
4. Every submit carries an idempotency key. The same key never creates a second order.
5. Broker fills are not trusted blindly: inconsistent fill data is flagged, not recorded.
6. One order type only: buy-to-open a single long option, limit price. No shorting, no spreads, no margin.

## Connecting a real broker

See [docs/BROKER_INTEGRATION.md](docs/BROKER_INTEGRATION.md). In short: implement `BrokerAdapter`,
subclass `BrokerConformance`, make the tests pass, then run it against a paper account.

## Open the dashboard

`python -m optplat` serves a dashboard at http://127.0.0.1:8800. Paste your `OPTPLAT_API_TOKEN`, then
**Run one cycle**. With the default demo market you can tick *Automatic entries* and *Save settings*
to watch positions open and close. The token is kept in `sessionStorage` for the tab only.

Environment variables (see `.env.example`):

| Variable | Meaning |
|---|---|
| `OPTPLAT_BROKER` | `sim` (default) or `ibkr_paper` |
| `OPTPLAT_DATA` | `demo` (default with `sim`) or `yahoo` (needs `pip install -e ".[yahoo]"`) |
| `OPTPLAT_ALLOW_UNVERIFIED_QUOTES` | `1` lets unofficial quotes through the risk gate. Research only |

## What is still missing

Real market data with verified timestamps, a connected paper broker, historical replay and a
strategy evaluation report, a daily loss halt, notifications, and an always-on deployment. The next
items are in [docs/BACKLOG.md](docs/BACKLOG.md). Paper results prove nothing about a real edge on
their own.

## AI agent contributions

`CLAUDE.md` defines what an AI agent may and may not change. Agents work on `agent/*` branches and
open pull requests for review. They never merge and never touch risk limits or live trading.
