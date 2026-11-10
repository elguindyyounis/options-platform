# Broker integration checklist

Target for the first real connection: an **Interactive Brokers paper account** through TWS or
IB Gateway, using `ib_async`. Nothing here has been run against a real account yet.

## Setup

1. Create/enable the paper account in IBKR and log into TWS or IB Gateway in **paper** mode.
2. In TWS/Gateway: *Global Configuration → API → Settings*: enable socket clients, keep
   "Read-Only API" **off** only on the paper session, and note the port (paper defaults: TWS 7497,
   Gateway 4002).
3. Check market-data permissions for US options on that account. Without them quotes will be empty
   or delayed.
4. `pip install -e ".[ibkr]"` and copy `.env.example` to `.env`:
   `OPTPLAT_BROKER=ibkr_paper`, `IBKR_PAPER_ACCOUNT=DU...`, `IBKR_PAPER_PORT=7497`.
   `ibkr_paper_config()` already refuses non-local hosts, non-paper ports and non-`DU` accounts.

## Methods to implement in `src/optplat/broker/ibkr.py`

| Method | What it must do |
|---|---|
| `healthcheck` | Connect read-only, confirm the configured `DU` account is in `managedAccounts()`. Never place orders |
| `get_account` | Net liquidation, cash, and cost basis of open long options |
| `get_positions` | Long option positions only, mapped to `OptionContract` |
| `get_quote` | Fresh bid/ask for the exact contract. Raise `QuoteUnavailable` if empty, zero-ask or delayed |
| `submit_limit_order` | BUY limit, DAY. Put `idempotency_key` in `orderRef`. Return the existing order if that ref already exists |
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
