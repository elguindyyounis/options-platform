# Broker integration: IBKR paper

Owner decision 2026-11-26 (CLAUDE.md hard rule 1): the platform may send orders to an **Interactive Brokers paper
account**, automatically, mirroring the main simulated account. `broker/ibkr.py` is implemented and passes the shared
conformance suite against a fake IB session. It has **not** yet run against a real paper account.

## Turning it on (owner)

1. Log into TWS (or IB Gateway) in **paper** mode. In *Global Configuration > API > Settings*: enable socket clients,
   and turn **"Read-Only API" off** (orders are refused while it is on). Paper ports: TWS 7497, Gateway 4002.
2. `pip install -e ".[ibkr]"`, then in the platform's environment set:
   `OPTPLAT_BROKER=sim`, `OPTPLAT_IBKR_MIRROR=1`. `IBKR_PAPER_ACCOUNT` is optional: unset, the account is read from TWS, and only when TWS manages exactly one account and it begins with `DU`.
   Optional `IBKR_ORDER_CLIENT_ID` (default 71). The Options Alerter shares this TWS and paper account and uses ids 91, 94, 95, 96 and 98, which are refused. Keep the account id out
   of git.
3. Restart the platform. It prints "IBKR paper mirror ON". `GET /api/health` shows `broker.ibkr_mirror` with the
   last outcome; every mirrored order, rejection, error and cancel is in the audit log as `ibkr_mirror_*`.

## Sharing the paper account with the Options Alerter

Both apps send orders to the same IBKR paper account. Every platform order's `orderRef` starts with `optplat:`; the
platform ignores every order without it, and sells only what its own orders bought (never the Alerter's positions).

## What it refuses (fail-closed, may only be made stricter)

- A host other than localhost; a port other than 7497 / 4002; a configured account not beginning with `DU`.
- A session where ANY managed account does not begin with `DU` (it disconnects without placing anything).
- Anything but a DAY limit order; more than 10 contracts or $5,000 premium per order; a sell larger than the paper
  account holds after its other working sells. Buys round the limit down to the cent, sells round it up.
- Orders the risk policy or kill switch rejected never reach the simulator, so they never reach IBKR either.

## How the mirror works

`MirroredSimBroker` (in `broker/mirror.py`) is the simulated broker plus a copy. The simulator remains the account of
record (fills, cash, positions, restart restore). Each order it accepts, and each cancel, is queued to one background
worker that sends it to IBKR paper with the same idempotency key (`orderRef`), so a resend after a crash finds the
existing order instead of placing a second. IBKR being closed, slow or rejecting an order is audited and never changes
the simulated account. A restart restores the simulator from the database and does not resend old orders.

## Still open

- No reconciliation report yet comparing IBKR paper fills with the simulator's (read the `ibkr_mirror_*` audit).
- Live-session check: run once during market hours with one liquid contract before trusting it.

## Methods to implement in `src/optplat/broker/ibkr.py`

| Method | What it must do |
|---|---|
| `healthcheck` | Connect read-only, confirm the configured `DU` account is in `managedAccounts()`. Never place orders |
| `get_account` | Net liquidation, cash, and cost basis of open long options |
| `get_positions` | Long option positions only, mapped to `OptionContract` |
| `get_quote` | Fresh bid/ask for the exact contract. Raise `QuoteUnavailable` if empty, zero-ask or delayed |
| `submit_limit_order` | BUY_TO_OPEN **or** SELL_TO_CLOSE limit, DAY (`intent.side`). Put `idempotency_key` in `orderRef`. Return the existing order if that ref already exists. Raise `BrokerRejected` when selling more than is held |
| `cancel_order` | Cancel and return the resulting status |
| `get_order_status` | Map IBKR status to `SUBMITTED / PARTIALLY_FILLED / FILLED / CANCELLED / REJECTED` |
| `find_order_by_client_id` | Search open and completed orders by `orderRef`. Return `None` only if truly absent |
| `get_open_orders` | Working orders only |

## Things that will bite you

- **Quote timestamps.** `Quote.timestamp_verified` must be `True` only when IBKR supplies the tick
  time. The default risk policy rejects unverified times. If you relax it for testing, do so
  consciously via `RiskPolicy(require_verified_quote_time=False)`.
- **Delayed data.** If the account only has delayed data, quotes are not executable prices. Treat
  that as `QuoteUnavailable`.
- **Optimistic paper fills.** IBKR's paper simulator can fill more generously than a real market.
  Keep the conservative `SimBroker` numbers as an audit comparison before trusting any P&L.
- **Timeouts.** If a submit times out, the order may still be live. The order manager already parks
  it in `ERROR_RECONCILE_REQUIRED`. `find_order_by_client_id` is what lets `reconcile()` resolve it.
- **Partial fills.** The manager supports `PARTIALLY_FILLED`. Make sure `filled_qty` and
  `avg_fill_price` are cumulative, not per-fill.
- **Reconnects.** After a restart, call `POST /api/paper/reconcile` before submitting anything new.
- **Contract resolution.** Qualify the contract with IBKR (conId, exchange, multiplier) before
  trading. Do not assume the OCC symbol resolves.

## Proving the adapter

Create `tests/test_ibkr_conformance.py`:

```python
from conformance import BrokerConformance
from optplat.broker.ibkr import IBKRPaperBroker

class TestIBKRConformance(BrokerConformance):
    def make_broker(self):
        return IBKRPaperBroker()

    def seed_quote(self, broker, bid, ask):
        pass  # real broker: choose a liquid contract and run during market hours
```

The shared tests use a fixed contract and prices, so adjust `tests/helpers.py` (or override the
tests) to a currently listed, liquid option when running against the live paper market. Mark these
tests so they only run when you ask for them, not in CI.

## Before trusting it

- Zero duplicate orders when you kill the process mid-submit and restart.
- Every order that reaches the broker has a matching `RISK_APPROVED` audit entry.
- The kill switch blocks new orders and still allows cancels.
- Run for several weeks of market sessions before drawing any conclusion about strategy quality.
