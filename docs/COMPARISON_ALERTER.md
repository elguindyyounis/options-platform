# Comparison with options-alerter (read-only, built by ChatGPT)

Maintained by the daily challenger. Alerter commit last reviewed: `9210fd8`.

## Modules read so far
* `core.py`: candidate scoring, deterministic "agents" (technical, flow, sentiment, entry,
  skeptic, CIO). Honest framing: scores "rank research opportunities, not likelihoods of profit".
  Missing quote or volume caps the score; the skeptic can veto but learning can only make things
  stricter. Black-Scholes greeks are labelled approximations (4% rate, no dividends).
* `entry_quality.py`: strict gate for real-source entries: spread <= 15% of ask, volume >= 20,
  OI >= 100, quantity <= 10% of volume and of OI, at most 2 per symbol+side, basket caps for market
  ETFs (3) and growth tech (4), strike-distance screens by horizon. Demo candidates are exempt.
* `liquidity.py`: volume/OI/spread/turnover score, PREFERRED/WATCH/THIN tiers, and an
  `exit_stress` that models extra bid concession (base / thin / stressed) from participation.

## Never read yet
`agents.py` (Ollama overlays; only the first lines seen), `storage.py`, `server.py`,
`data_sources.py`, `agent_skills/*`, `adaptive.py`, `feedback.py`, `strategy_lanes.py`,
`paper_engine.py`, `risk.py`.

## Where the alerter is stricter or more honest
* Participation: it refuses entries above 10% of reported volume and OI. The platform's sim broker
  fills any quantity at ask + 0.5%, and its sizing only looks at premium. (Addressed display-only
  on 2026-11-13; see CHALLENGES.md.)
* Exit friction: it stress-tests the bid with extra concession when size is large vs volume. The
  platform has one flat 0.5% slippage.
* Learning cannot relax vetoes; the platform has no learning, so nothing to compare.

## Where the platform is stricter
* Fail-closed risk engine with kill switch, quote-age and verified-quote-time checks, order state
  machine with reconcile, and a hard PAPER-only OrderManager.
