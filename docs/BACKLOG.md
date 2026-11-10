# Backlog

Ordered by priority. Agents: take the first item that is not **BLOCKED** and does not need a human
decision (see `CLAUDE.md`). Move finished items to Done with the PR link.

## Direction: a self-improving research platform (owner, 2026-11-11)

Goal: a paper-first research platform that keeps challenging its own decisions, measures what worked,
and tests better approaches, with entries and exits automated in paper mode only. Principles:

* Improvement is a research loop. A hypothesis and its pass criteria are written down **before** results
  exist, a challenger runs in shadow mode against an unchanged frozen baseline, and it is judged only
  by those criteria (minimum trade counts, out-of-sample split). Promotion, risk limits and the
  evaluation criteria belong to the owner. An agent never edits its own grading.
* Trading logic stays deterministic. Reasoning is a structured record (inputs, thresholds, the
  assumption relied on) stored per decision and joined to outcomes later. Language models review and
  propose hypotheses offline; they never place orders, and every order passes the risk gate.
* No signal is used by a strategy until it has shown predictive value in the framework.
* Free Yahoo data is delayed, unofficial, and updates open interest once a day. True unusual-activity
  detection needs licensed trade-level data (blocked on the owner). GEX is model-dependent.

## Next up

1. **Dashboard question audit.** Every panel states the trading question it answers; remove or redesign
   those that do not help a decision.
2. **Weekly research agent.** Proposes experiments from the journal and evaluation results, runs them in
   shadow mode, and writes a report for the owner to approve.

Existing items, in order:

3. **Trailing stop exit.** Optional trailing stop alongside the fixed take-profit/stop-loss, off by
   default, with tests for ratchet behaviour and unobservable quotes.
4. **Audit view.** Dashboard panel and endpoint for the audit log of a selected order.
5. **Storage hygiene.** Schema version table and a simple migration runner; indexes on
   `orders(state)`; paginate `list_orders`.
6. **CI hardening.** Add `ruff` and a type check (`mypy` or `pyright`) to the workflow; fix what
   they find without changing behaviour.

## Blocked on a human

* **Validating any signal.** `VALIDATED_SIGNALS` in `signals.py` is empty. Adding a name is the owner's
  decision, after `study_signal` and a pre-registered experiment support it.

* **Daily loss halt.** Stop new entries once equity is down X% from the day's start; exits keep
  working. Needs the owner to choose X (a risk-limit default) before anyone builds it.
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
* Replay provider: `ReplayDataProvider` (no look-ahead), `ReplayClock`, `run_replay` drives the real
  engine over recorded snapshots in a throwaway store; reproducible via `ReplayResult.fingerprint()`.
* Strategy evaluation report: `evaluate()` / `python -m optplat.evaluate`; in-sample vs out-of-sample
  segments, drawdown, do-nothing and buy-and-hold context, MEASURED only above minimum trade counts.
* Data-quality gate (roadmap step 1): `dataquality.py` drops crossed, zero-ask, non-finite, expired and
  duplicate rows, rejects stale/future/bad-price snapshots, flags frozen feeds, logs every issue.
* Decision journal (roadmap step 2): append-only record of every entry, exit and rejected/not-chosen
  candidate with rationale, provenance and assumptions; forward outcomes of candidates from recorded
  snapshots (UNOBSERVABLE rather than guessed); `/api/journal`, `/api/journal/summary`, dashboard panel.
* Champion/challenger (roadmap step 3): `research.py`; frozen baseline by fingerprint, append-only
  hashed pre-registered hypotheses, criteria floors, confirmatory runs on post-registration data only,
  one final verdict, `python -m optplat.research register|evaluate|list`.
* Options signals (roadmap step 4): `signals.py` volume/OI and unusual-activity flags, call/put ratios,
  liquidity tiers, coverage, partial-chain GEX with stated assumptions; all UNVALIDATED, a strategy
  cannot use one until the owner adds it to `VALIDATED_SIGNALS`; `study_signal` and
  `python -m optplat.signals scan|study`; `/api/signals/{symbol}`.
* Runner health: seconds since last good cycle and a stalled flag (3x interval) on `/api/health`
  (no error text) and `/api/engine/status` (with error); dashboard shows LOOP STALLED.
