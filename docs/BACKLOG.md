# Backlog

Ordered by priority. Agents: take the first item that is not **BLOCKED** and does not need a human
decision (see `CLAUDE.md`). Move finished items to Done with the PR link.

## Next up

1. **Replay provider.** A `ReplayDataProvider` that serves recorded snapshots in time order, plus a
   fake clock, so the real engine can be run over history deterministically. Test that a replay run
   is reproducible.
2. **Strategy evaluation report.** A script/endpoint that runs the engine over recorded or replayed
   data and reports trades, costs, drawdown, and a comparison against a do-nothing baseline.
   Require a minimum trade count and an out-of-sample split before any number is called "result".
3. **Daily loss halt.** Stop new entries for the rest of the day once equity is down a configurable
   percent from the day's start (default conservative, e.g. 2%). Exits keep working. New policy
   field, engine guard, tests. (The default value is a risk decision: propose it in the PR.)
4. **Runner health.** Expose time since last successful cycle and last error on `/api/health`; show
   a "stalled" warning in the dashboard when no cycle has completed in 3x the interval.
5. **Trailing stop exit.** Optional trailing stop alongside the fixed take-profit/stop-loss, off by
   default, with tests for ratchet behaviour and unobservable quotes.
6. **Audit view.** Dashboard panel and endpoint for the audit log of a selected order.
7. **Storage hygiene.** Schema version table and a simple migration runner; indexes on
   `orders(state)`; paginate `list_orders`.
8. **CI hardening.** Add `ruff` and a type check (`mypy` or `pyright`) to the workflow; fix what
   they find without changing behaviour.

## Blocked on a human

* **Real broker adapter (IBKR paper).** Owner is implementing `broker/ibkr.py`. Do not start it.
* **Licensed, timestamped options data.** Needs an account and budget decision.
* **Earnings and event blackout.** Needs a trustworthy event-calendar source.
* **2027 NYSE holiday table.** Needs an official source; the clock fails closed for unknown years.
* **Risk-limit tuning, strategy promotion.** Owner decisions, driven by evidence from items 1-3.

## Ideas (unscheduled)

* Recorder storage: snapshots are about 20 KB of JSON each. At the default 5-minute interval and two
  symbols that is roughly 3 MB a day (about 90 MB for the 30-day default). Compress, or store only
  rows near the money, before running a short interval or a long watchlist.

* Per-sector concentration limit once a sector map exists.
* Notification hook (email/webhook) for kill-switch, stalled runner, unresolved orders.
* Multi-leg support is deliberately out of scope until single-leg paper results are understood.

## Done

* Foundation: models, fail-closed risk engine, order state machine with reconcile, broker contract,
  simulated broker, conformance tests, token-protected API.
* MVP: sell-to-close, exit policy, demo/static/Yahoo data providers, baseline strategy, market
  clock, trading engine + runner, same-underlying concentration limit, re-entry cooldown, dashboard.
* Quote and snapshot recorder: every snapshot the engine sees is stored (labelled real or fictional,
  with source and time), retention setting, hourly prune, dashboard count.
