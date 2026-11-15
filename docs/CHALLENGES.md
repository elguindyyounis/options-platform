# Challenges (platform vs. alerter)

Last alerter commit reviewed: `0107246`

## Open challenges

| # | Challenge | Needs owner? |
|---|---|---|
| 1 | No commissions/fees in paper fills; results look better than reality. Needs a fee model value. | Yes (cost assumption) |
| 2 | Win/loss stats on few trades. Partly addressed by `/api/results` sample gate; the evaluation report (backlog 2) should add an out-of-sample split. | No |
| 3 | Alerter judges many lanes on few trades; platform has one strategy but no multiple-testing note once variants exist. | No |
| 4 | Open-position losses are invisible in `/api/results`; add mark-to-market equity once the recorder has quotes. | No |

## Run log

* 2026-11-15: First run. Added `evaluation.py` and `GET /api/results`: closed-trade summary that
  returns no win rate for zero trades, flags samples under 30 trades, shows P&L without the best
  trade, and lists limitations. Display only; no trading behaviour changed.
