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
4. **Runner health on `/api/health`** (the authenticated `/api/engine/status` runner block now has it, see Done). Remaining: decide whether the unauthenticated `/api/health` should expose any of it (default: no).
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

* Liquidity/size-vs-volume entry check modelled on the alerter's `liquidity.py` (risk change: owner decision).

* Fee/commission model for the sim broker (needs an owner-chosen cost assumption).
* Dashboard UX steps (one per run): top candidates and why-taken/skipped from cycle data; per-account view (alerter-only data); upcoming calendar (needs event source); Node UI contract test like the alerter's.

* Per-sector concentration limit once a sector map exists.
* Notification hook (email/webhook) for kill-switch, stalled runner, unresolved orders.
* Multi-leg support is deliberately out of scope until single-leg paper results are understood.

## Done

* Runner health server-side: `Runner.status()` reports last success/failure, failure streak, seconds since success and `stalled`; glance uses it (2026-11-16, run 12).

* Glance strip states market open/closed, warns when the market-hours check is off and when a running loop looks stalled (client-side; server-side runner health, item 4, still open).

* Candidates show volume/open interest ("not reported" when null); skip reasons separate unreported from low liquidity data; display only.

* Dashboard "At a glance" strip (safety, activity, what needs the owner) built from existing API data; tested under node.

* Modeled net GEX: `optplat/gex.py`, cycle report `gex`, dashboard panel with assumption label; display only.

* Top candidates: cycle report `candidates` (top 3 per symbol, best 10) and a dashboard panel; display only.

* Dashboard Results panel (`/api/results` shown with sample-size verdict, split-half, unrealized n/a handling; textContent only).

* Split-half stability check in `/api/results` (`split_half_check`): earlier vs later half of closed trades, withheld below the sample gate. Not an out-of-sample test.

* Open-position marks in `/api/results` (`summarize_open_positions`): bid-based, verified and fresh quotes only, null total if any position is unmarkable.

* Closed-trade summary (`evaluation.py`, `GET /api/results`): sample-size gate, null win rate for zero trades, best-trade concentration, closed-only drawdown, limitations list. Partial progress on item 2 (no out-of-sample split or baseline comparison yet).

* Foundation: models, fail-closed risk engine, order state machine with reconcile, broker contract,
  simulated broker, conformance tests, token-protected API.
* MVP: sell-to-close, exit policy, demo/static/Yahoo data providers, baseline strategy, market
  clock, trading engine + runner, same-underlying concentration limit, re-entry cooldown, dashboard.
* Quote and snapshot recorder (branch `agent/2026-11-10-quote-recorder`): every `MarketSnapshot` and
  held-position quote the engine sees is stored in SQLite (`market_snapshots`, `market_quotes`) with
  recorded-at time, provider `as_of`, source, verified flag and fictional flag. `record_market_data`
  (default on) and `record_retention_days` (default 90, 0 = forever) are engine config.
* Fill-model label on `/api/results` and the Results panel (run 11, challenge 7/9); no equity curve yet.
