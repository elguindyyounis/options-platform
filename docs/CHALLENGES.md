# Challenges to the platform

Last alerter commit reviewed: `1fc88f18f2875bb115f8264700a9835cebe45c80`

## Open challenges

| ID | Challenge | Needs owner? | Status |
|----|-----------|--------------|--------|
| C2 | Entry gate has no volume / open-interest / participation checks (alerter: vol>=20, OI>=100, qty <=10% of each). Quote model has no volume/OI fields. Adding a gate that rejects more is tightening, but needs a model change. | No (tightening) | Open |
| C3 | Sim exit is bid minus flat 0.5% regardless of spread or size. Alerter models THIN/STRESSED exit concessions. A research-only stress table in the report would show how fragile P&L is. | No | Open |
| C4 | Many lanes/symbols judged on few trades. Per-underlying breakdown now exists with per-slice sample labels (2026-11-13). Still missing: per-exit-reason slice (engine does not store the exit reason on the order; `note` is a fixed string) and per-lane slice. | No | Partly done |
| C7 | Alerter `sizing.py` shrinks position size while few comparable closed trades exist (<10 samples caps fraction, <20 caps evidence). Platform sizing is fixed regardless of sample. Would be a risk-sizing change. | Yes (sizing) | Parked |
| C5 | Strike-distance-from-spot screen (alerter 30/40/60% by DTE) missing from the platform strategy. Changes what is traded. | Yes (strategy behaviour) | Parked |
| C6 | Alerter skeptic/"council" gating has no platform analogue; not adopting without evidence. | Yes | Parked |

## Closed

| ID | Challenge | Run |
|----|-----------|-----|
| C1 | `/api/report` printed a win rate and realized P&L after a single trade with only a text caveat. Added display-only `evidence` block: sample-size status (<30 closed trades = INSUFFICIENT_SAMPLE), Wilson 95% win-rate interval, P&L excluding best trade, depends-on-best-trade flag. | 2026-11-13 |

## Run log

| Date | Alerter reviewed to | Challenged | Changed |
|------|--------------------|------------|---------|
| 2026-11-13 (run 5) | `1fc88f1` (no new commits) | Results sliced by symbol would invite cherry-picking on tiny slices | `slice_results` in `evidence.py`, `by_underlying` in `/api/report`, closed rows carry `underlying`, dashboard note, tests. Read alerter `sizing.py`. |
| 2026-11-13 | `1fc88f1` (first scan; no prior marker) | Win rate/P&L shown with no sample context | `evidence.py`, report + dashboard label, tests |
