# Challenges to the platform

Last alerter commit reviewed: 48ccf71 (first review; the whole history was out of scope, only the
modules listed in `COMPARISON_ALERTER.md` were read).

## Open challenges

| ID | Challenge | Needs owner? |
|----|-----------|--------------|
| C2 | Fills use one flat slippage (0.5%) regardless of spread, size or volume. Add a research-only exit-stress table (bid concession scenarios, quantity versus volume/OI) as the alerter's `exit_stress` does. Needs volume and OI on `Quote` or the chain data; check what the providers expose first. | No |
| C3 | No per-strategy or per-lane tagging of trades, so many ideas could be judged on a few trades each. Add a candidate/strategy tag to the report and warn when many groups each have under 30 trades. | No |
| C4 | Synthetic demo market: confirm every API/dashboard surface labels results as fictional, not just the startup banner. | No |
| C5 | Report reads only the latest 1000 orders; older closed trades silently drop out of stats. Report the truncation. | No |
| C6 | Closed-trade stats ignore unrealized losses on open positions. Add open-position bid-mark drawdown to the report. | No |

## Done

* C1: `/api/report` presented a bare win rate and P&L, so one winning trade read as "100% win
  rate". Added `stats` (profit factor, closed-trade drawdown, Wilson 95% win-rate range, best-trade
  share of wins, `SAMPLE_TOO_SMALL` under 30 trades) and the dashboard shows the range and warning.
  Display only; no trading behaviour changed.

## Run log (newest first)

| Date | Alerter commit | What was done |
|------|----------------|---------------|
| 2026-11-15 | 48ccf71 | First run. Read `liquidity.py` and `strategy_performance.py`. Landed C1 on `agent/2026-11-15-report-sample-honesty`. |
