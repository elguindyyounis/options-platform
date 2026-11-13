# Challenges to the platform

Last alerter commit reviewed: `1fc88f1` (Improve pull request CI stability and preflight parity (#27))

## Open challenges

| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | `report()` showed a win rate with no sample-size context (1 win of 1 trade = 100%) | No | Mitigated 2026-11-13: `evidence` block added |
| 2 | Paper fills carry no commissions or per-contract fees, so net P&L is optimistic | Decision on fee values | Open |
| 3 | No counterfactual record of rejected or missed setups (alerter's `feedback.py` has one) | No | Open: fits backlog item 1 (recorder) |
| 4 | Heuristic registry: nothing says which strategy constants are unvalidated guesses | No | Open |
| 5 | Quote-age bound: confirm `require_verified_quote_time` also rejects stale-but-stamped quotes | No | Open: check `risk.py` |
| 6 | Drawdown / daily loss halt absent | Yes (default value) | Open: backlog item 4 |
| 7 | `report()` reads only the newest 1000 orders; older trades silently drop | No | Flagged via `evidence.truncated`; real fix is pagination (backlog item 8) |
| 8 | Results cannot be tagged synthetic vs real source per trade | No | Open: needs source on orders |

## Run log (newest first)

| Date | Branch | What |
|------|--------|------|
| 2026-11-13 | `agent/2026-11-13-evidence-context` | First run. Added `evidence.py` and an `evidence` block in `report()`. |
