# Challenges raised against the platform

Last alerter commit reviewed: `9210fd8a16b10fb622790cc7dd82980c74a6af08`

Nothing here is evidence of an edge. Paper results on simulated fills prove nothing.

## Open challenges

| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Entry fills are modelled at the ask plus slippage; the platform has no fill-rate or exit-slippage stress, so results lean optimistic. Alerter has `liquidity.exit_stress` (not yet read). | No (research table) | Open |
| 2 | Baseline strategy has no thin-contract cap (alerter caps score for volume<5, OI<20, spread>20%). Changing what trades. | Yes (strategy/risk behaviour) | Open |
| 3 | Many lanes/policies compared on few trades: no multiple-comparison note anywhere. Needed before backlog item 3 (evaluation report). | No | Open |
| 4 | Label inference (e.g. direction from a single trend filter) is treated as fact in strategy output; needs an explicit "inferred" tag. | No | Open |
| 5 | Exit assumptions (fills at bid, immediate) have no stress test. | No | Open |
| 6 | Stale-quote age limit: alerter rejects >30 min old fetches; confirm the platform's `require_verified_quote_time` path covers the same. | No (read only) | Open |

## Closed

| # | Challenge | Resolution |
|---|-----------|-----------|
| 0 | `/api/report` showed win rate and P&L with n=1 and silently dropped closed trades once >1000 orders existed. | 2026-11-13: added `evidence` block (sample status, Wilson 95% interval, P&L without best trade, underlyings, truncation flag); dashboard hides win rate below 30 trades. |

## Run log (newest first)

| Date | Alerter commit | What was challenged | What changed |
|------|----------------|--------------------|--------------|
| 2026-11-13 | 9210fd8 | Report overstated confidence from tiny samples; silent truncation | `evidence_summary` in `orders.py`, dashboard text, tests. Branch `agent/2026-11-13-report-evidence` |
