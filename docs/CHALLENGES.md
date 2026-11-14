# Challenges

Last alerter commit reviewed: 1fc88f1

## Open challenges
| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Paper exits assume flat 0.5% slippage even in wide markets; results may look better than real exits | No | Stress helper added 2026-11-14 (display-only); not yet shown in API/dashboard or applied to any report |
| 2 | Pause new entries when existing held options have no usable bid mark (alerter does this) | Yes (changes entry behaviour / risk policy) | Open, not started |
| 3 | No shadow-exit comparator to test whether early exits beat fixed exits | No | Open |
| 4 | No minimum-sample guard on any per-strategy/lane statistic | No | Open; belongs with BACKLOG item 3 |

## Run log (newest first)
| Date | Branch | What |
|------|--------|------|
| 2026-11-14 | agent/2026-11-14-exit-stress | First run. Added `stress.py` (exit-friction scenarios, research only) with 5 tests; created these docs. |
