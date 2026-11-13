# Challenges to the platform

Last alerter commit reviewed: 1fc88f18f2875bb115f8264700a9835cebe45c80

## Open challenges
| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Report shows win rate on any sample size | no | Mitigated 2026-11-13 (sample_status, Wilson interval); consider hiding win rate entirely under the minimum |
| 2 | Closed trades in the report are not tagged with data source (demo vs Yahoo) | no | Open |
| 3 | Exit fills are modelled at bid minus 1% limit; check replay would not give a better fill than real markets allow | no | Open, needs replay (backlog 2) |
| 4 | Strategy has no per-parameter-set trade counts; many lanes judged on few trades invites cherry-picking | no | Open |
| 5 | Daily loss halt default is a risk decision | yes | Blocked on owner |

## Run log (newest first)
| Date | Alerter commit | Challenged | Changed |
|------|----------------|------------|---------|
| 2026-11-13 | 1fc88f1 | Report win rate with no sample-size context | Added stats.py, report fields sample_status / win_rate_ci95_pct / payoff stats, dashboard text |
