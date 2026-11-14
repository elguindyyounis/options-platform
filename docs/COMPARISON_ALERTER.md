# Comparison with options-alerter (ChatGPT-built, private, read-only)

Reviewed at alerter commit `1fc88f1` (2026-11-14). Statements below come from reading code, not from
the owner's database, which agents cannot see.

## Modules read so far

`core.py`, `agents.py`, `paper_engine.py` (exit manager), `exit_decisions.py` (fill model),
`liquidity.py` (`exit_stress`), `risk.py` (first 80 lines), `storage.py` (`paper_close`, schema).

## Never read yet (read one per run)

`server.py`, `data_sources.py`, `adaptive.py`, `feedback.py`, `sizing.py`, `strategy_lanes.py`,
`intraday_strategy.py`, `gex.py`, `unusual_activity.py`, `daily_review.py`, `agent_lab.py`,
`research_foundations.py`, `entry_quality.py`, `agent_skills/`, rest of `risk.py` and `storage.py`.

## Where the alerter is stricter or more honest

* **Liquidity-aware exit price.** `exit_decisions.py` marks exits at bid minus base slippage minus a
  liquidity penalty that grows with spread over 15%, and with order size versus volume and open
  interest (capped at 40%). The platform's `SimBroker` applies only a flat `slippage_pct` to bid, so a
  wide-spread contract is exited as cheaply as a tight one. Logged as an open challenge (C2).
* **Stress scenarios** (`liquidity.exit_stress`): BASE_BID / THIN_MARKET / STRESSED_EXIT, labelled
  "illustrative, not measured depth". The platform has nothing equivalent.
* **Learning cannot loosen** (`core.research_case`): adaptive scores and journals may only add a
  stricter hold, never remove a veto. Worth keeping as a design rule if the platform ever adds learning.
* **Skeptic veto and 7-agent review** are required by `risk.evaluate`; the platform has a plain
  deterministic strategy instead. Different design, not necessarily better: the agent scores are
  explicitly "not calibrated likelihoods".
* **Quote age** check on entries (30 min). The platform is stricter (60 s on exits).

## Where the platform is stricter or better

* Order state machine with reconcile, idempotency, and a broker contract with conformance tests.
* Exit quotes that are stale, crossed or zero-bid are UNOBSERVABLE rather than priced.
* `OrderManager` refuses non-PAPER adapters.

## Weak spots seen in the alerter (for the owner, not changed here)

* `Store.paper_close` accepts any non-negative `exit_price` from the caller; the concession lives in
  `exit_decisions`, so a manual close can bypass it.
* Learning/adaptive stats are computed over `trade_journal` rows with no visible minimum-sample gate in
  the parts read so far (not yet checked in `adaptive.py`).
