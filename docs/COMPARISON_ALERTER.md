# Comparison with options-alerter

The alerter (owner's other repo, built by ChatGPT, private, read-only to agents) is a larger
research scanner. This file records what was read and what it does differently. Code and tests only:
agents cannot see the owner's database, so nothing here says how either system performed.

## Read so far
* `core.py`, `agents.py`: deterministic scoring plus six "specialist" reports and a skeptic veto.
  Scores are labelled ranking heuristics, not probabilities. An optional local LLM can only make
  decisions more cautious. Many "agents" are rule functions over the same candidate dict, so their
  agreement is not independent confirmation (the code says so for same-source OHLCV features).
* `strategy_performance.py`: per-lane closed-trade summary with profit factor, closed-trade-only
  drawdown, null win rate when there are no trades, and explicit `limitations` text. Also has an
  import path for competitor paper trades that refuses to name a winner.
* `liquidity.py`: contract volume/OI/spread tiers and an exit-stress scenario that widens the exit
  concession with order size relative to volume and OI.
* `lane_paper_engine.py` (skimmed): fills are ask+friction in, bid-friction out; marks older than a
  max age make equity null instead of guessed.
* `storage.py` (header only): single SQLite file, one connection per operation.

## Still unread
`server.py`, `data_sources.py` (beyond function list), `adaptive.py`, `feedback.py`, `sizing.py`,
`gex.py`, `sector_rotation.py`, `trade_confluence.py`, `agent_skills/*`, remaining lane modules.

## Where the alerter is stricter or more honest
* Reports win rate as null, not 0, with no trades; carries a `limitations` string on every summary.
* Models exit liquidity versus size (platform fills any size at ask+0.5%; see CHALLENGES #2).
* Marks stale quotes as unobservable. The platform does this too (`mark_quality`).

## Where the platform is stricter
* Single audited order state machine, idempotency keys, fail-closed pre-trade risk, refusal of any
  non-PAPER adapter, token-protected API.
* Quote timestamps carry an explicit `timestamp_verified` flag; the alerter says its are unverified.
