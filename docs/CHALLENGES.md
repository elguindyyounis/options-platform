# Challenges to the platform

Last alerter commit reviewed: 1fc88f18f2875bb115f8264700a9835cebe45c80

## Open challenges

| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Sim fills full size at the touch regardless of volume/OI; paper P&L can look better than a real fill. | No | Labelled in entry reports (2026-11-14). Not yet shown in dashboard or used to haircut fills. |
| 2 | Platform stores no `is_demo` flag per order/position; demo and real-data results could mix in one DB. Alerter stores it. | No | Open |
| 3 | No minimum-sample rule when judging results (backlog item 3 covers this). | No | Open |
| 4 | Alerter's `exit_stress` bid-concession scenarios have no platform equivalent; exits fill at bid minus 0.5% always. | No | Open |
| 5 | Whether to make fills actually harsher for oversized orders changes paper results. | Yes | Owner decision |

## Run log (newest first)

| Date | Branch | What |
|------|--------|------|
| 2026-11-14 | agent/2026-11-14-fill-realism-tags | First run. Created these docs. Added display-only `fill_realism` tags on entry reports. |
