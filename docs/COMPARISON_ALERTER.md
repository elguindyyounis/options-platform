# Comparison with options-alerter

Written by the daily challenger from reading the alerter's code (private repo, read-only). The
alerter's database lives on the owner's machine and has not been seen, so nothing here says
anything about real results. Demo data is fictional.

Alerter commit reviewed at creation: `1fc88f1`.

## What the alerter does that the platform did not (as of 2026-11-14)

| Area | Alerter | Platform |
| --- | --- | --- |
| Order size vs depth | `entry_quality.py` rejects an order above 10% of reported volume or open interest | Strategy has minimum volume/OI, but `size_quantity` sizes only by premium; no participation check. Now *displayed* (not enforced), see `liquidity.py` |
| Exit friction | `liquidity.exit_stress` models bid concessions (base, thin, stressed) | Sim broker fills the bid minus a flat 0.5%; no depth-aware stress. Now displayed per entry |
| Concentration | Per-symbol/side cap plus basket caps (SPY/QQQ/IWM = 3, growth tech = 4) | Per-underlying/side cap of 2 only; no basket cap |
| Strike geometry | Rejects strikes far from spot, horizon-specific (30/40/60%) | Strategy limits moneyness to 5% (stricter) |
| Honesty labels | Every output carries `status: SCENARIO_ONLY`, `limits`, `dealer_sign_verified: False`, `is_demo` | Partly: rationale notes "no demonstrated edge"; no per-field provenance |
| Lanes | `strategy_lanes.py`: separate virtual accounts per horizon, `data_validated: False`, equity left `None` when positions lack a mark | Single account |
| Learning/audit | `trade_journal`, `feedback.py` counterfactuals, `agent_lab` sequence log | Audit log per order only |
| Atomic admission | `paper_buy_atomic` re-checks candidate staleness, kill switch, quality, in one `BEGIN IMMEDIATE` | `OrderManager` + risk engine; comparable intent |

## Where the alerter is looser than the platform

* Quote freshness for new entries: up to 1800 s (and `-120 s`) in `paper_buy_atomic`; the platform
  allows 60 s and requires a broker-verified quote time by default. Yahoo times are unverified in both.
* Exit price in `paper_close` is whatever the caller supplies (`exit_price >= 0`); the platform's sim
  broker derives it from the bid minus slippage.
* Missing volume is coerced to `0` when building rows (`int(finite_num(..., 0))`), so "unknown" and
  "zero" are indistinguishable downstream.
* Lane `risk_budget_pct` values (1.5/2.0/1.0) are far above the platform's 1% per position default;
  owner has chosen these, not changed here.

## Modules read so far

`liquidity.py`, `entry_quality.py`, `agents.py`, `core.py` (scoring, greeks), `strategy_lanes.py`,
`storage.py` (`paper_buy_atomic`, `paper_close`, schema), `data_sources.py` (`option_rows`).

## Never read yet (read one per run)

`server.py`, `feedback.py`, `adaptive.py`, `agent_lab.py`, `exit_decisions.py`, `gex.py`,
`sizing.py`, `research_foundations.py`, `intraday_strategy.py`, `daily_review.py`,
`unusual_activity.py`, `market_clock.py`, `risk.py`, `paper_engine.py`, other `agent_skills/`.
