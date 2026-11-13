# Challenges to the platform

Last alerter commit reviewed: 1fc88f18f2875bb115f8264700a9835cebe45c80 (re-checked 2026-11-13 again, no new commits)

## Open challenges
| # | Challenge | Needs owner? | Status |
|---|-----------|--------------|--------|
| 1 | Report shows win rate on any sample size | no | Mitigated 2026-11-13 (sample_status, Wilson interval); consider hiding win rate entirely under the minimum |
| 2 | Closed trades in the report are not tagged with data source (demo vs Yahoo) | no | Mitigated 2026-11-13: intents carry `data_source`, report tags entry/exit source and groups `by_data_source`. Orders placed before this change show UNKNOWN. |
| 3 | Exit fills are modelled at bid minus 1% limit; check replay would not give a better fill than real markets allow | no | Open, needs replay (backlog 2) |
| 4 | Strategy has no per-parameter-set trade counts; many lanes judged on few trades invites cherry-picking | no | Open |
| 6 | Headline realized P&L ignored open positions still held at a loss, and `/api/report` silently read only the latest 1000 orders | no | Mitigated 2026-11-13: `marked_pnl`, `open_unrealized_pnl`, `marked_pnl_complete`, `history_truncated` |
| 5 | Daily loss halt default is a risk decision | yes | Blocked on owner |

## Run log (newest first)
| Date | Alerter commit | Challenged | Changed |
|------|----------------|------------|---------|
| 2026-11-13 | 1fc88f1 (unchanged) | Realized-only P&L hides open losers; report truncation was silent | Added marked P&L, unobservable-mark count, history_truncated flag, dashboard text. Read alerter `exit_decisions.py`: unobservable quote means no exit decision (platform already matches) |
| 2026-11-13 | 1fc88f1 (unchanged) | Closed trades not tagged demo vs real; pooled stats could mix sources | Added OrderIntent.data_source, report entry/exit_data_source, by_data_source, data_sources_mixed, dashboard note |
| 2026-11-13 | 1fc88f1 | Report win rate with no sample-size context | Added stats.py, report fields sample_status / win_rate_ci95_pct / payoff stats, dashboard text |
