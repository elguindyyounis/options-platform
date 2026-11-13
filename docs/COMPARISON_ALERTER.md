# Comparison with options-alerter

`options-alerter` is the owner's other repo (built by ChatGPT, read-only here). This file records what
has been read and what it does differently. Alerter code is flat Python at the repo root; the platform
is a package under `src/optplat/`. Last alerter commit reviewed: `1fc88f1` (see `docs/CHALLENGES.md`).

## Read so far

`core.py` (scoring, Greeks), `risk.py`, `paper_engine.py`, `liquidity.py`, `adaptive.py`,
`feedback.py`, `research_foundations.py`, `server.py` (security checks only, via grep).

## Never read yet (read one per run, then move it up)

`agents.py`, `storage.py`, `data_sources.py`, `gex.py`, `unusual_activity.py`, `sizing.py`,
`exit_decisions.py`, `agent_lab.py`, `daily_review.py`, `agent_skills/*`, `deploy/`, `tradingview/`.

## Where the alerter is stricter or more honest than the platform

* **Sample gating on learning.** `adaptive.calibration` is off below 5 real closed trades, ignores
  demo data, caps each trade's return at +/-100%, shrinks cohorts toward zero (12 pseudo-samples) and
  caps the total score change at 7 points. (Five trades is still very few; its own docs say
  "observational only".) The platform had no such context on its results until this run's
  `evidence.py`.
* **Provenance table.** `research_foundations.SIGNALS` labels every signal `UNVALIDATED` and says who
  chose each weight. The platform has no equivalent registry of what is a heuristic.
* **Counterfactual journal.** `feedback.py` records rejected and missed setups at 1/7/30-day horizons,
  valued ask-in, bid-out, and labels them "never actual fills". The platform records no rejects.
* **Quote age.** `risk.evaluate` rejects a quote fetched more than 30 minutes ago or in the future.
  The platform has `require_verified_quote_time`; check separately that it also bounds quote age.
* **Drawdown halt.** `max_drawdown_pct` (default 30) blocks new entries. The platform has none
  (backlog item 4, which needs an owner-approved default).
* **Entry spread cap** of 35% of ask and an exit-stress model in `liquidity.py`.
* **Origin check.** `server.py` rejects cross-origin POSTs and bad Host headers. The platform checks
  Host and requires a header token, which a cross-site page cannot send, so this is covered, but note it.

## Where the platform is stricter

State machine with reconcile, idempotency keys, a broker contract and conformance tests, refusal of
non-PAPER adapters, sell-to-close only against held positions, and a fail-closed `OrderManager`.

## Weak spots seen in the alerter (for context, not to copy)

* `risk.evaluate` repeats the "Unknown quote source" check twice (harmless duplicate).
* Winners and losers are not netted of option commissions anywhere that was read.
