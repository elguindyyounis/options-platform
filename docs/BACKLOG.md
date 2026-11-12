# Backlog

Ordered by priority. Agents: take the first item that is not **BLOCKED** and does not need a human
decision (see `CLAUDE.md`). Move finished items to Done with the PR link.

## Next up

1. **Quote and snapshot recorder.** Persist every `MarketSnapshot` / `Quote` the engine sees into
   SQLite (new table, with timestamps and source). This is the raw material for honest replay and
   is the most valuable thing the platform can accumulate. Include a retention setting and tests.
2. **Replay provider.** A `ReplayDataProvider` that serves recorded snapshots in time order, plus a
   fake clock, so the real engine can be run over history deterministically. Test that a replay run
   is reproducible.
3. **Strategy evaluation report.** A script/endpoint that runs the engine over recorded or replayed
   data and reports trades, costs, drawdown, and a comparison against a do-nothing baseline.
   Require a minimum trade count and an out-of-sample split before any number is called "result".
4. **Daily loss halt.** Stop new entries for the rest of the day once equity is down a configurable
   percent from the day's start (default conservative, e.g. 2%). Exits keep working. New policy
   field, engine guard, tests. (The default value is a risk decision: propose it in the PR.)
5. **Runner health.** Expose time since last successful cycle and last error on `/api/health`; show
   a "stalled" warning in the dashboard when no cycle has completed in 3x the interval.
6. **Trailing stop exit.** Optional trailing stop alongside the fixed take-profit/stop-loss, off by
   default, with tests for ratchet behaviour and unobservable quotes.
7. **Audit view.** Dashboard panel and endpoint for the audit log of a selected order.
8. **Storage hygiene.** Schema version table and a simple migration runner; indexes on
   `orders(state)`; paginate `list_orders`.
9. **CI hardening.** Add `ruff` and a type check (`mypy` or `pyright`) to the workflow; fix what
   they find without changing behaviour.

## Blocked on a human

* **Real broker adapter (IBKR paper).** Owner is implementing `broker/ibkr.py`. Do not start it.
* **Licensed, timestamped options data.** Needs an account and budget decision.
* **Earnings and event blackout.** Needs a trustworthy event-calendar source.
* **2027 NYSE holiday table.** Needs an official source; the clock fails closed for unknown years.
* **Risk-limit tuning, strategy promotion.** Owner decisions, driven by evidence from items 1-3.

## Ideas (unscheduled)

* Record the liquidity review with the order/audit log and show it on the dashboard (display only).
* Owner decision: gate entries on participation of reported volume/OI (alerter uses 10%).

* Per-sector concentration limit once a sector map exists.
* Notification hook (email/webhook) for kill-switch, stalled runner, unresolved orders.
* Multi-leg support is deliberately out of scope until single-leg paper results are understood.

## Done

* 2026-11-12 (branch `agent/2026-11-12-liquidity-review`): display-only entry liquidity review and bid-concession exit stress in the engine entry report (`liquidity.py`). No gate or size changed.

* Foundation: models, fail-closed risk engine, order state machine with reconcile, broker contract,
  simulated broker, conformance tests, token-protected API.
* MVP: sell-to-close, exit policy, demo/static/Yahoo data providers, baseline strategy, market
  clock, trading engine + runner, same-underlying concentration limit, re-entry cooldown, dashboard.
