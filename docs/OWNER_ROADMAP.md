# Owner roadmap (2026-11-17, live request): bigger improvements, and a platform both of us can learn from

The owner asked the challenger agent to stop making only one small change per run and to build larger, useful pieces, while
still challenging the platform, the alerter and the agents. Hard rules in `CLAUDE.md` still apply (paper only, no loosened safety
control, no weakened test, no fake data). Items are ordered; take the first not done and not blocked.

| # | Item | Status |
| --- | --- | --- |
| 1 | **Market context page**: calls vs puts (volume, premium, open interest) for index funds and mega-caps with a fixed, declared reading; modeled gamma per strike, call wall, put wall, gamma flip; net-gamma heat map per ticker; gamma chart and price chart with the levels; expected move from the ATM straddle; upcoming earnings and FOMC | Done 2026-11-17 (`context.py`, `/api/context`, Context page). Real Yahoo data not seen from the cloud; unvalidated |
| 2 | **Context history**: store the per-ticker context each scan (already in `scan_results`) and chart sentiment and net-gamma over days, so the owner sees change, not a snapshot | Open |
| 3 | **Strategy accounts page**: each option lane and the 10x challenge side by side: equity, trades, hit rate with the sample warning, harder-exit P&L, what is currently being tuned. Platform data only; alerter data lives on the Mac | Open |
| 4 | **Agent conversation page**: per decision, what each committee agent said (vote, reason, veto), where they disagreed, and what happened after. Reads `decisions` and the committee output | Open |
| 5 | **Decision feed**: every entry, skip and exit with the reason in plain words, newest first, linking to the trade | Open (`why skipped` panel exists on Desk) |
| 6 | **Research progress glance** (shadow book gate, independent observations, hypotheses registered/resolved) on the Desk | Open (UX-1) |
| 7 | **Earnings expected-move history**: record the straddle before each earnings date and the actual move after, so "expected value change" is checked against what happened | Open; needs an earnings date source (Yahoo calendar is unofficial) |
| 8 | **Weekly challenge page**: how the platform and each agent was challenged this week, what failed, what changed, and the P&L effect with the sample caveat | Open; `weekly.py` exists |
| 9 | **Learn-from-it layer**: a "what to look at today" note per page, plain-words glossary on hover, and an "explain this number" line stating its assumption | Open |

Principles: show the assumption next to every number; say plainly when the sample is too thin; never present modeled or demo data
as real; every new display says which decision it helps.
