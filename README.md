# options-platform

A small, broker-ready foundation for a **paper-first** options trading platform. It is the plumbing
(risk gate, order lifecycle, broker adapter contract, audit trail) and not a trading strategy.

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

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # 55 tests

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

## Not included yet

Strategy and signal generation, market-data ingestion, historical replay/backtesting, a frontend,
position exits, multi-user auth, and an always-on deployment. Paper results from any of this prove
nothing about a real edge on their own.
