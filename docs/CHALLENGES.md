# Challenges to the platform

Last alerter commit reviewed: `9210fd8`

## Open challenges
| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Sim fills ignore size vs volume/OI (optimistic fills). Tags added; still no enforcement or depth-aware slippage. | Enforcement/slippage model: yes (sizing/risk) | Tags landed 2026-11-13 |
| 2 | Alerter's `exit_stress` scenarios (thin / stressed bid concession) have no platform equivalent; exits assume a flat 0.5% slippage. | No (research table) | Open |
| 3 | Basket caps (market ETFs, growth tech) are not in the platform's concentration limit, which is per underlying only. | Yes (risk policy) | Open |
| 4 | Quote/volume provenance: Yahoo volume and OI may be delayed; reports should show data age next to results. | No | Open |
| 5 | Any evaluation (backlog 3) must report sample size and refuse to call small samples results. | No | Open |

## Run log (newest first)
| Date | Alerter reviewed | Change | Branch |
|------|------------------|--------|--------|
| 2026-11-13 | `9210fd8` (first review; no prior baseline) | Participation tags on entry cycle reports | agent/2026-11-13-fill-participation-tags |
