# Comparison with the owner's other project (options-alerter)

Read-only comparison by the daily challenger. The alerter is private and was built with ChatGPT; this
file records only what was read in code, never the owner's real data. Alerter HEAD at first review:
`9210fd8` (15 commits).

## Read so far
`core.py`, `risk.py`, `strategy_lanes.py`, `research_foundations.py`, `agents.py` (first 70 lines),
`storage.py` (schema/defaults only), `sizing.py` (first 50 lines).

## Not yet read (next runs pick one)
`agents.py` (rest), `storage.py` (rest), `server.py`, `data_sources.py`, `paper_engine.py`,
`adaptive.py`, `feedback.py`, `liquidity.py`, `entry_quality.py`, `exit_decisions.py`, `gex.py`,
`unusual_activity.py`, `intraday_strategy.py`, `daily_review.py`, `agent_skills/*`.

## What the alerter does differently
* **Honest labelling everywhere.** Every signal is listed in `research_foundations.SIGNALS` with an
  origin and a `validation` field (`UNVALIDATED`, `OBSERVATIONAL_ONLY`, ...). Score weights are called
  "developer hypotheses". Promotion of a strategy revision is hard-coded `BLOCKED`, with reasons.
* **Sample-size gates.** The retrospective protocol needs >=20 distinct test days and >=40 cases,
  splits by *date* not by row, and warns that 7-day outcomes on neighbouring dates overlap.
* **Per-lane accounts.** `strategy_lanes.py` keeps isolated virtual cash per lane and refuses to
  report equity when any position lacks a mark (`paper_equity_usd = None`). The platform's `/api/report`
  already marks open positions at the bid and shows "unobservable", which matches this.
* **Quote-quality caps.** `candidate_score` caps scores for thin volume/OI or wide spreads so a tiny
  denominator cannot top a ranked list. The platform's strategy has no equivalent yet.
* **Fail-closed council.** Seven agent reports must all match the current quote snapshot; an LLM can
  only add vetoes, never upgrade a rejection.
* **Stale quote age.** Rejects fetches older than 30 min or >2 min in the future.
* **Slippage default 0.5% on entry** (applied to the ask). Exits are not discussed in the files read.

## Where the alerter is weaker or unclear (code-level only)
* `retrospective_protocol` compares two policies on the same test slice with no multiple-comparison
  control and no confidence interval, so the "difference" it prints has no stated uncertainty.
* Lane risk budgets are stored per lane but the lane ledger has no entry path that is validated here.
* Not verified: anything about runtime behaviour or the owner's database.
