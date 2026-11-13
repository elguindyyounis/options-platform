# Challenges to the platform

Last alerter commit reviewed: `9210fd8a16b10fb622790cc7dd82980c74a6af08`

## Open challenges
| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Sim sells at bid minus flat 0.5%, so paper P&L is optimistic for wide/thin/large trades | no | Stress module added; wiring into a report is open |
| 2 | No counterfactual journal for rejected/unselected setups (alerter has one) | no | Open |
| 3 | Reports must not call a number a result without a minimum trade count and out-of-sample split | no | Open (BACKLOG item 3) |
| 4 | Quotes carry no volume/open interest, so depth stress treats depth as unknown (harshest) | needs data decision if a paid feed | Open |

## Run log (newest first)
| Date | Branch | What |
|------|--------|------|
| 2026-11-13 | agent/2026-11-13-exit-stress | Added research-only `stress.py` exit-liquidity stress + 9 tests; created these docs |
