# Challenges to the platform

Last alerter commit reviewed: 48ccf71 (first review; the whole history was not diffed, see COMPARISON_ALERTER.md)

## Open challenges
| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Results showed a bare win rate on any sample size. | No | Mitigated 2026-11-15: report has `stats` with Wilson 95% interval and sample label. |
| 2 | Simulated fills ignore order size vs volume/OI: 50 contracts on a 50-volume contract fills at ask+0.5%. Optimistic. | Partly: tightening fills is fine, new defaults are a risk decision | Open. Idea: record participation (qty/volume) on each fill as a display tag first. |
| 3 | Entry and exit are judged lane-less on few trades; no per-strategy-version breakdown. | No | Open. |
| 4 | Win-rate interval assumes independent trades, but overlapping positions in one underlying are correlated. | No | Documented in `stats.limitations`; no fix. |
| 5 | Report only reads the latest 1000 orders; older trades silently drop from stats. | No | Open. |
| 6 | Drawdown is closed-trade only, no unrealized. | No | Labelled in `stats.limitations`. |

## Run log
| Date | Alerter commit | Change | Branch |
|------|----------------|--------|--------|
| 2026-11-15 | 48ccf71 | Sample-size honesty block in `/api/report` and dashboard | agent/2026-11-15-sample-honesty |
