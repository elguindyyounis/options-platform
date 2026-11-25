# Evidence-driven dashboard audit and redesign

Owner mandate: November 26, 2026. All changes are paper-only. Display rank has
no allocation, promotion, sizing or execution authority.

## Audit findings and disposition

| Surface | Trader decision | Finding | Implemented response |
| --- | --- | --- | --- |
| Global header | Can these prices support a decision? | Real + Demo blended source provenance and execution mode | Separate evidence-gated data label, Paper Execution, session status, connection and latest valid quote receipt |
| Overview | Where should attention go first? | Incumbent received the largest card by implementation order | Health, isolated-book risk, grouped leaderboard, champion status, held positions, opportunities, rejections, then research detail |
| Performance | Which strategy is ahead under comparable assumptions? | Native balances used different capital, sizing and start dates; incumbent omitted from lane comparison | Include incumbent and every options account, group $100K books separately from small-account experiments; show native and common-risk results separately |
| Champion | Is a lead validated? | No comparable holdout paths support a champion | Explicitly show no validated champion; proposed promotion/demotion evidence is inspectable and has no automatic effect |
| Portfolio and positions | What exposure and exit evidence exists? | Missing option marks could be mistaken for a hold thesis or current equity | Retain missing/unverified status and exit review access; do not sum separately funded virtual balances |
| Scanner and Builder | What can pass admission now? | Cached alternate-source pass labels could look actionable | Current source veto is recomputed; eligible and rejected research are separate; no synthetic dataset switch |
| Unusual activity and GEX | What does this evidence imply? | Turnover and dealer-sign models can be over-interpreted | Retain turnover/assumption labels and incomplete coverage; IBKR sample does not authorize full-chain GEX |
| Agents | Which evidence and veto caused this decision? | Council output is heuristic unless an actual model ran | Preserve actual recorded reasons; no invented discussion or trained-model claim |
| Experiments, daily, learning, feedback and Lab | What changed, and did it improve outcomes? | Proposals competed for the first screen | Keep hypothesis, timeline, failures and evidence in accessible drilldowns below current trading decisions |
| Integrations and automation | Is the installed system current and healthy? | Green CI alone did not verify the local app; production provider selection leaked into staged tests | Verify installed build and service build; stage tests pin their isolated fixture provider, preserving runtime IBKR config |
| Small-screen use | Can health and leader be understood without a wide table? | Dense comparisons need space | Responsive health cards and stacked leader/champion summaries; horizontal scrolling confined to tables |

## Comparison contract

`strategy_comparison.py` is a pure, read-only recorded-fill overlay, vendored
unchanged in Claude for consistency. No research calculation creates a ledger
entry or modifies native history. Each book receives $100,000 comparison
capital, a $1,000 premium limit per entry, $10,000 total open premium and $2,000
per underlying. Only integer contracts fit; capital remains reserved until the
recorded exit time. All books use $0.65 per contract each way and an additional
0.5% price concession each way on recorded effective fills.

The common interval starts at the latest first recorded non-synthetic entry
among active books. This sacrifices earlier observations rather than comparing
different periods. Future exits cannot free capital. Unavailable partial-exit
cash-flow paths, unaffordable contracts, invalid evidence and synthetic rows are
excluded and counted. Zero comparable trades is **not measured**, not a 0% win.

Metrics: net common-risk P&L, return on identical comparison capital, expectancy,
closed-outcome drawdown, profit factor, net/deployed-premium capital efficiency,
entry frequency per calendar day and independent underlying-days. Profit factor
is undefined without observed losses. Full mark-to-market drawdown cannot be
reconstructed without complete bid paths and remains unavailable.

Rank uses realized overlay P&L minus the full remaining open premium. This is a
conservative display score, not an independently validated performance estimate.
Recorded native fills still reflect different opportunity sets, original
admission constraints and possible historical cost-model differences. An overlay
cannot manufacture an identical-BBO, identical-opportunity experiment. Native
ledger results remain visible beside the overlay, with their own capital/sample.

## Champion review policy

The displayed criteria require a frozen pre-registration, 60 forward sessions,
30 closed trades, 20 independent underlying-days, at least 10 later-holdout
trades, verified BBO paths, trial-adjusted clustered uncertainty, best-three-win
removal and execution stress, and frozen drawdown/risk limits. Independent data
or risk failure suspends execution; deterioration is reviewed against the
pre-registered holdout, not recent leaderboard luck. This is a proposed review
policy. No strategy was promoted or demoted by this release.

## Synthetic isolation and validation

Claude startup defaults to market research data. Synthetic data requires an explicit test-fixture flag and an in-memory database. Direct test providers remain available for isolated software tests. Its trade-view history cap is disclosed: a truncated source cannot name an observed leader. Native capital is not inferred when the trade view does not carry it. The common algorithm is vendored identically from Alerter; the Claude adapter does not implement or deploy an IBKR broker.

Validation includes complete preflight, comparison math/capital tests,
future-time and exclusion tests, dynamic feed-state evidence tests, synthetic
admission rejection, and meaningful replacement of the old incumbent-first UI
assertions with the requested hierarchy. Desktop visual review and responsive layout checks
use a read-only preview backed by actual recorded data; all writes are disabled.
Installed Alerter verification follows reviewed final-head CI, stable promotion
and the existing ledger-preserving updater. Claude changes remain unmerged PRs.
