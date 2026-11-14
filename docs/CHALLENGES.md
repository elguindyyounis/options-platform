# Challenges to the platform

Maintained by the daily challenger run. Last alerter commit reviewed: `1fc88f18f2875bb115f8264700a9835cebe45c80`

You cannot see the owner's database; challenges come from code, tests and demo data only.

## Open challenges

| # | Challenge | Needs owner? | Status |
|---|---|---|---|
| 2 | The platform only records trades it took. Rejected and missed setups are never marked later, so we cannot tell whether risk gates help (alerter `feedback.py` does this). | No, but depends on backlog 1 (quote recorder) | Open |
| 3 | `strategy_lanes` in the alerter judges many lanes on few trades each. Check whether the platform could ever do this (it has one strategy today) and add per-strategy sample labels before a second strategy is added. | No | Open |
| 4 | Simulated fills ignore commissions and any quote movement between decision and fill. Reports say "simulated" but model no fee. | Owner decides fee assumption | Open |
| 5 | A sell order's `cost_basis` comes from the position average. Check partial-fill cost basis behaviour with tests. | No | Open |

## Closed challenges

| # | Challenge | Resolution |
|---|---|---|
| 1 | `/api/report` printed a bare win rate: one winning trade read as 100%, and orders beyond the read limit silently vanished. | Added `evidence` block (sample verdict, Wilson 95% interval, best-trade share, truncation flag). Branch `agent/2026-11-14-evidence-labels`. |

## Run log (newest first)

| Date | Alerter commits new | Challenge | Outcome |
|---|---|---|---|
| 2026-11-14 | None known (first run; baseline `1fc88f1`) | #1 bare win rate and silent truncation in report | Display-only `evidence` block + 6 tests; docs created |
