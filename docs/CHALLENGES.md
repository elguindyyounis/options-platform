# Challenges (platform vs alerter)

Last alerter commit reviewed: 1fc88f18f2875bb115f8264700a9835cebe45c80

## Open challenges
| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Sim entry fill ignores order size vs contract volume/OI; large size in thin contracts looks too good. Add a display-only size-vs-liquidity flag on fills/report. | No | Open |
| 2 | No exit-friction stress on open positions or closed trades (alerter `exit_stress`). Add display-only stressed P&L. | No | Open |
| 3 | Win rate shown with no sample-size context. | No | Done 2026-11-14 (INSUFFICIENT_SAMPLE label, Wilson 95% range, P&L without best trade) |
| 4 | Report shows no per-lane/per-strategy breakdown; when lanes exist, judge each on its own n. | No | Open (platform has no lanes yet) |
| 5 | Whether sizes/limits are sensible. | Yes | Owner decision; not touched |

## Run log (newest first)
* 2026-11-14: first run. Alerter had no prior review baseline; read liquidity.py, agents.py, part of core.py.
  Landed challenge 3 on branch `agent/2026-11-14-sample-honesty`.
