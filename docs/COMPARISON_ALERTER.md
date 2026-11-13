# Comparison with options-alerter (read-only, built by ChatGPT)

Notes from reading the alerter's code. Claims here come from code only; the owner's database was not seen.

## Read so far
* `core.py` (2026-11-13): deterministic `candidate_score` and `research_case` (six reviewers plus a sizing agent).
  Notable: scores are labelled "ranked heuristic, not an empirical edge"; a candidate with no volume or ask is capped
  at 34; thin contracts (volume < 5, OI < 20, spread > 20%) are capped at 52-56 so tiny-denominator volume/OI ratios
  cannot dominate; a Skeptic veto (invalid quote, spread > 35%, DTE < 7, no volume, unknown source) cannot be
  reversed by learning. Demo candidates are flagged `is_demo` and always downgraded to at best PASS-with-caveat.
* `agents.py` (2026-11-13): optional local Ollama overlay. Localhost-only endpoint; the model may only make things
  more cautious (VETO/HOLD), never upgrade. Headlines are marked untrusted. No equivalent concern in the platform yet
  because it has no LLM layer.
* `adaptive.py` (partly): learning needs >= 5 closed REAL-source trades, each cohort needs >= 3, per-trade returns are
  clipped to +/-100%, adjustment capped at +/-7 points, demo trades never train real candidates.
* `storage.py` (headings only): `BEGIN IMMEDIATE` around buys and closes, i.e. atomic admission.

## Where the alerter is stricter or more honest
* Explicit minimum sample sizes before anything is "learned". The platform had none: `/api/report` showed a win rate
  from one trade with no qualification. (Addressed 2026-11-13 by `stats.py`, display only.)
* Demo data cannot contaminate real-source statistics. The platform keeps demo and real in separate runs but its report
  does not tag which data source produced a closed trade.
* Liquidity caps on score; a veto layer that learning cannot override.

## Where the platform is stricter
* Every order passes a fail-closed risk engine and an order state machine with reconcile; the alerter's paper fills
  assume the ask (conservative) but have no state machine for partial fills.
* Quote timestamp verification is required by default.

## Never read yet
`server.py`, `data_sources.py`, `storage.py` (body), `feedback.py`, `exit_decisions.py`, `strategy_lanes.py`,
`sizing.py`, `agent_lab.py`, `daily_review.py`, `entry_quality.py`, `risk.py`, and all `agent_skills/*`.
