# Challenges to the platform

Last alerter commit reviewed: `9210fd8a16b10fb622790cc7dd82980c74a6af08`

## Open challenges
| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Sim sells at bid minus flat 0.5%, so paper P&L is optimistic for wide/thin/large trades | no | Stress module added; wiring into a report is open |
| 2 | No counterfactual journal for rejected/unselected setups (alerter has one) | no | Journal module + tests added; engine does not call it yet (engine change, needs review) |
| 3 | Reports must not call a number a result without a minimum trade count and out-of-sample split | no | Gate module `oos.py` + tests added (chronological split, withheld test window, bad rows counted); not wired into a report |
| 6 | Many lanes are watched and the best is quoted; chance of a lucky lane is not shown | no | `best_of_k_null_prob` added; not wired into the dashboard |
| 5 | Alerter-style cohort scoring lets 3-trade cohorts move rankings and shows win rates with no interval; avoid copying that into the platform | no | Noted; sample gate in the new journal is the pattern to reuse |
| 4 | Quotes carry no volume/open interest, so depth stress treats depth as unknown (harshest) | needs data decision if a paid feed | Open |

## Run log (newest first)
| Date | Branch | What |
|------|--------|------|
| 2026-11-13 | agent/2026-11-13-daily-challenger-2 | Added research-only `oos.py` (out-of-sample gate, best-of-k luck probability) + 8 tests; read alerter risk.py, agents.py, part of data_sources.py. Alerter unchanged since last review |
| 2026-11-13 | agent/2026-11-13-counterfactual-journal | Added research-only `counterfactual.py` (pending/NO_DATA/evaluated cases, sample gate) + 8 tests; read sizing.py, adaptive.py. Alerter unchanged since last review |
| 2026-11-13 | agent/2026-11-13-exit-stress | Added research-only `stress.py` exit-liquidity stress + 9 tests; created these docs |
