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

0. **Challenger agent's list.** The open challenges (counterfactual journal, display-only GEX, stressed lane P&L,
   signal provenance doc) live in `docs/CHALLENGES.md`; the daily agent takes one per run.

1. **Schedule the weekly report.** `python -m optplat.weekly` exists; running it on a timer and where the
   owner reads it (file, email, notification) is the owner's choice.

2. **Use scan results.** Let unusual-activity and most-active names feed the committee's sentiment agent and, if the owner
   wants, an auto-managed watchlist (single stocks need a known earnings date). Record scan chains for replay.
2b. **Swing lane, next steps.** Register it as a pre-registered experiment with pass criteria, compare it with the frozen
   baseline on the same days, record daily bars for honest replay, and decide with the owner whether a version should trade
   options with 7 to 45 days to expiry (that fits the risk policy; it needs an owner decision to promote).
3. **Short-term lane, next steps.** The EMA9/VWAP lane exists (Done). Next: register it as a pre-registered
   experiment with pass criteria, record intraday bars for honest replay, and add a second rule to compare. Real intraday
   option fills need the owner to change the risk policy's 7-day minimum and a real-time quote source.
4. **Scale in and out of held positions.** The committee sizes new entries between 10% and 100% of the
   engine cap and learns that share from outcomes. Trimming a loser or adding to a winner needs exit-manager
   support (partial sell orders; adds must still pass the risk gate and its per-order and total-premium caps).
5. **Agent coverage the owner can unblock.** News sentiment needs a data source. The events agent covers
   earnings and FOMC only; CPI, jobs data, dividends and index events need a source. Earnings dates come
   from Yahoo's unofficial calendar and are unverified, so a paid or official earnings feed would be better.

Existing items, in order:

6. **Trailing stop exit.** Optional trailing stop alongside the fixed take-profit/stop-loss, off by
   default, with tests for ratchet behaviour and unobservable quotes.
7. **Audit view.** Dashboard panel and endpoint for the audit log of a selected order.
8. **Storage hygiene.** Schema version table and a simple migration runner; indexes on
   `orders(state)`; paginate `list_orders`.
9. **CI hardening.** Add `ruff` and a type check (`mypy` or `pyright`) to the workflow; fix what
   they find without changing behaviour.

## Blocked on a human

* **Validating any signal.** `VALIDATED_SIGNALS` in `signals.py` is empty. Adding a name is the owner's
  decision, after `study_signal` and a pre-registered experiment support it.

* **Daily loss halt.** Stop new entries once equity is down X% from the day's start; exits keep
  working. Needs the owner to choose X (a risk-limit default) before anyone builds it.
* **Real broker adapter (IBKR paper).** Owner is implementing `broker/ibkr.py`. Do not start it.
* **Licensed, timestamped options data.** Needs an account and budget decision.
* **Earnings and event blackout.** Needs a trustworthy event-calendar source.
* **FOMC table beyond 2027.** `events.py` fails closed for later dates. Add a year only from federalreserve.gov.
* **2027 NYSE holiday table.** Needs an official source; the clock fails closed for unknown years.
* **Risk-limit tuning, strategy promotion.** Owner decisions, driven by evidence from the research loop.

## Ideas (unscheduled)

* Two functions named `liquidity_tier` exist with different signatures: `liquidity.py` takes `(volume, open_interest, spread_pct)` and returns PREFERRED/WATCH/THIN; `signals.py` takes `(spread_pct, volume, oi)` and returns A/B/C. Every call site is correct today, but swapping the import would silently mis-tier everything, since all arguments are numbers. Rename one (display-only, no threshold change) and add a test that pins each order.
* Write the stressed-exit scenario as its own audit event at close time (the alerter does), so a result can be re-checked later.
* Recorder storage: snapshots are about 20 KB of JSON each. At the default 5-minute interval and two
  symbols that is roughly 3 MB a day (about 90 MB for the 30-day default). Compress, or store only
  rows near the money, before running a short interval or a long watchlist.

* Per-sector concentration limit once a sector map exists.
* Notification hook (email/webhook) for kill-switch, stalled runner, unresolved orders.
* Multi-leg support is deliberately out of scope until single-leg paper results are understood.

## Done

* Exit quote age recorded on option-lane closes and tagged `STALE_EXIT_QUOTE` (challenge 8). Follow-ups: show it in the dashboard; do the same for share lanes.
* Lane summaries report stressed-exit realized P&L beside the bid-exit total over the same trades (API only; dashboard display is a follow-up).

* Frozen baseline lane (challenge 3): `frozen-baseline-options`, a literal copy of the first short-term rule, settings pinned by `FROZEN_FINGERPRINT` and a test. Simulated only.
* 10x challenge account (owner request 2026-11-13): `challenge.py`, restartable, critic on every trade, attempt history, dashboard panel.
* Alerter comparison (owner request 2026-11-12): `docs/COMPARISON_ALERTER.md`, liquidity tiers and exit stress in post-mortems
  (`liquidity.py`), and `docs/CHALLENGES.md` as the log for the daily challenger agent. Open challenges are listed there.
* Options-first research (owner request 2026-11-12): scanner v2 (200-name sector-mapped universe, very-low-open-interest rule,
  weekly expirations, last-trade buy/sell inference, next-day open-interest confirmation with a day-by-day memory), sector
  heat map and sentiment, five simulated option lanes (short-term base and aggressive, swing base and aggressive, unusual
  flow that stuck) beside the share lanes as benchmarks, automatic post-mortems with a digest, per-sector caps. Options
  page on the dashboard. Research only: no orders, `RiskPolicy` untouched.
* Swing research lane: pullback-in-uptrend on daily bars, simulated share trades, own stops, earnings-aware, off by default.
* Short-term research lane: EMA9/VWAP on 5-minute bars, simulated share trades in a separate ledger, off by default.
* Dashboard v2: six pages, trade blotter with per-trade files (reasoning, agent votes, exit, audit trail), market scan
  views, agent record, phone layout. No PR chores.
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
* Dashboard question audit (roadmap step 5): every panel states the trading question it answers (a test
  fails on a section without one); a "can I trust this right now" panel replaces three plumbing lines;
  equity/drawdown curve recorded per cycle while trading is allowed (kept apart for fictional vs real data),
  with a sample-size notice against the 30-trade minimum; positions show exit levels and days to expiry;
  experiments panel reads pre-registered hypotheses; duplicated per-cycle table removed.
* Weekly research report (roadmap step 6): `weekly.py`, `python -m optplat.weekly`; read-only, rule-based
  summary of data health, paper results, decisions, forward outcomes and experiments, plus questions worth
  a pre-registered test (data reliability, a dominant risk rejection, ranking vs passed-over candidates),
  each with its evidence and sample-size caveat. It registers nothing and never proposes loosening a limit.
* Agent committee (owner direction 2026-11-11: experimental, adaptive, no promotion step): `agents.py`
  (technical, volatility, options-sentiment, execution, exposure, skeptic), `committee.py` (decision, sizing,
  learning, scorecard, lessons), `committee_mode` off/shadow/active, `/api/committee`, dashboard panel.
  Weights and trust are refit from 4 h outcomes of every journaled vote, including rejected candidates, and
  every change is logged in `agent_weights`. Bounds: it can refuse or take less than the engine cap, never more.
* Event and earnings agent: `events.py` (FOMC decision days from the Fed's published calendar, earnings from
  Yahoo's unofficial calendar, unknown is never treated as safe) and the `events` gate in the committee: unknown
  earnings for a single stock is a hard veto, earnings within 5 days is a learnable veto, later earnings and
  an FOMC decision tomorrow weigh against; the skeptic now reports which calendar gaps remain.
* Scanner and trade ledger: `scanner.py` (most-active names, unusual option activity, fixed universe),
  `trades.py` (entries matched to exits with reasoning), `/api/scan`, `/api/trades`.
* Open-P&L completeness (2026-11-14): `report()` counts unobservable and wide-spread open marks and says when open P&L is incomplete. Open: show it on the dashboard; owner to decide on pausing entries while held marks are unreliable.
* Open-interest window honesty (2026-11-13): follow-ups and flow-lane trades carry `oi_sessions` and `oi_window_clean`. Open: owner to decide whether the flow lane should require a clean one-session window.
* Signal provenance page with a test that keeps it in step with `SIGNAL_NAMES`, `VALIDATED_SIGNALS` and the lane list (2026-11-14, branch `agent/2026-11-14-challenger-b`).
* Options-lane dashboard shows stressed-exit P&L beside bid-exit P&L and says how many open trades have no usable bid (2026-11-14, challenges 4 and 9). Display only. Still open: share-lane equivalents.
* Lane participation split (2026-11-14, run 5, challenge 11): lane summaries gain `participation`, closed option-trade P&L split by whether size stayed within 10% of reported volume and 10% of open interest (the alerter's entry caps), unknown counted as outside; shown on the options-lane Realized figure. A yardstick, not a gate: no lane rule or size changed. Open: share lanes have no volume figure, so none.
