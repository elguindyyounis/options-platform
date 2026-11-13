# Comparison with options-alerter (read-only, ChatGPT-built)

Reviewed at alerter commit `1fc88f1`. First pass by the daily challenger (2026-11-13).

## What the alerter does differently

* **Entry quality gate** (`entry_quality.py`): strict real-source entry policy. Spread <=15% of ask,
  volume >=20, OI >=100, strike distance from spot by DTE horizon, 10% volume/OI participation caps,
  per-symbol/direction and basket caps (market ETFs, growth tech). The platform only has a generic
  concentration limit and spread/staleness checks; it has no volume/OI/participation checks.
* **Liquidity stress** (`liquidity.py`): scores volume/OI/spread and models exit with extra bid
  concession in BASE / THIN / STRESSED scenarios. The platform's sim exit is bid minus flat slippage.
* **Honesty plumbing** (`feedback.py`, `strategy_lanes.py`): counterfactual returns are labelled
  "indicative ask-to-bid marks, NEVER actual fills"; lane accounts refuse to show equity while any
  option is open without a quote; "no invented positions or fills". Platform marks unobservable
  positions as UNOBSERVABLE (same spirit).
* **Fail-closed risk** (`risk.py`): requires fresh quote (<30 min), sizing agent proposal, skeptic PASS;
  pauses entries if held options lack reliable bid marks.
* **Optional local LLM overlay** (`agents.py`): can only add vetoes, never upgrade a rejection.

## Read this run

`risk.py`, `liquidity.py`, `entry_quality.py`, `strategy_lanes.py`, `paper_engine.py`, parts of
`feedback.py` and `agents.py`.

## Read in run 5 (2026-11-13): `sizing.py`

* Sizing is an ordinal "evidence index" explicitly labelled NOT a win probability; `calibrated_probability` is None.
* Fewer than 20 real-source closed comparable trades caps the index at 0.78; fewer than 10 caps the size fraction (0.60, or 0.45 for balanced). Sizing is more conservative when evidence is thin; the platform sizes the same regardless (see CHALLENGES C7, owner decision).
* yfinance candidates have quantity capped by 10% volume/OI participation and re-checked by the entry-quality gate; drawdown >=10%/20% shrinks size. Goals never raise risk (`goal_affects_size: False`).
* Sizing returns NO_TRADE unless the skeptic says PASS and the CIO says SUBMIT_FOR_RISK.

## Read in run 6 (2026-11-13): `storage.py`

* SQLite in WAL mode, busy_timeout 10s, foreign keys on; orders have a UNIQUE idempotency key and the paper buy runs in one atomic transaction that rechecks the drawdown limit at fill time (`paper_buy_atomic`).
* `trade_journal` stores per-trade `entry_reviews`, `exit_reason`, `exit_quote_at` and `return_pct`, so the alerter can attribute results to exit reasons. The platform did not store the exit reason until run 6.
* Not compared: whether the platform rechecks risk limits inside the same transaction as the fill (worth a look in a later run).

## Still never read

`core.py` (beyond header), `server.py`, `data_sources.py`, `adaptive.py`,
`daily_review.py`, `exit_decisions.py`, `gex.py`, `unusual_activity.py`, other
`agent_skills`.

## Where the alerter is stricter or more honest

* Liquidity participation (volume/OI) gates and exit-friction stress: platform lacks both
  (see CHALLENGES C2, C3).
* The alerter's lane ledger has no reporting of win-rate at all; the platform did print a win rate
  after one trade (fixed this run, C1).
