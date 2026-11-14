# Challenges to the platform

Last alerter commit reviewed: `1fc88f18f2875bb115f8264700a9835cebe45c80` (2026-11-14)

## Open challenges

| ID | Challenge | Needs owner? | Status |
|----|-----------|--------------|--------|
| C1 | Report showed win rate and P&L with no sample-size warning; one lucky trade looks like an edge | No | Done 2026-11-14: `sample` block on `/api/report` (display only) |
| C2 | Exit fills use flat slippage; wide-spread or thin contracts exit as cheaply as liquid ones, so paper P&L is optimistic. Alerter adds a liquidity penalty | Yes if it changes the fill model used by lanes; a display-only stress table does not | Open: next candidate is a display-only `exit_stress` table in the report |
| C3 | Win rate / P&L are pooled; per-lane or per-strategy slices judged on a handful of trades would look noisier than shown | No | Open: reuse `sample_quality` per slice once strategies are tagged |
| C4 | Entries fill at ask plus slippage, but there is no check that the sim quote was fresh at fill time in `SimBroker` (engine checks only on exits) | No, tightening | Open: needs reading `engine._run_entries` |
| C5 | Dashboard does not yet render the new `sample` block | No | Open |

## Run log (newest first)

| Date | Alerter commit | Challenged | Changed |
|------|----------------|------------|---------|
| 2026-11-14 | 1fc88f1 | C1 small-sample honesty; found C2 | `optplat/stats.py`, `sample` block in `/api/report`, tests; comparison doc created |
