# Challenges to the platform

Last alerter commit reviewed: 48ccf7112c960fad3622a634d858accd7aa00d49

Each row is a place where a result could look better than it is, or where the alerter is stricter.

## Open challenges

| # | Challenge | Needs owner? | Status |
|---|---|---|---|
| C7 | Alerter `trade_journal` stores `exit_quote_at` and `exit_reason` per closed trade, so exit quote staleness is auditable. Platform closed rows carry neither. Idea: add both to report rows (display only). | No | Open, next candidate |
| C3 | Fixed take-profit/stop-loss evaluated only on cycle ticks; a gap through the stop fills at the worse bid in reality, the sim exits at the observed bid but nothing reports slippage vs the trigger. Idea: record trigger price vs fill. | No | Open |
| C4 | Baseline strategy is one lane on one trend rule; many tweaks tried on few trades would overfit. Needs the evaluation report (BACKLOG 3) with an out-of-sample split before any tuning. | No | Open, blocked on BACKLOG 1-2 |
| C5 | Alerter treats Yahoo `fetched_at` as quote time but says so loudly; check the platform's Yahoo provider does the same and never sets `timestamp_verified=True`. Not yet read. | No | Open, verify |
| C6 | Alerter lane sizes are very large for experiments. Owner has chosen them; not changed here. | Yes | Noted only |

## Resolved

| # | Challenge | Resolution |
|---|---|---|
| C1 | Headline equity valued unquotable positions at cost (hid losses); win rate shown with no sample warning. | 2026-11-15: `/api/report` gains `sample`, `marks_complete`, `open_unmarked`, `conservative_equity`; dashboard shows them. Display only; risk sizing still uses broker equity (a risk-policy question, left for the owner). |

| C2 | No exit-friction stress: exits assume the bid is hittable at size. | 2026-11-15 (run 2): per-position `exit_stress` scenarios and report-level `stressed_equity` (spread-only; no volume/OI on `Quote`, so thin-market risk is understated). Display only. |

## Run log (newest first)

| Date | Alerter commit | Challenged | Changed |
|---|---|---|---|
| 2026-11-15 (run 2) | 48ccf71 (no change) | C2 exit-friction stress; read alerter `storage.py` head | `exit_stress()` + `stressed_equity` in `/api/report`, dashboard line, 2 tests |
| 2026-11-15 | 48ccf71 | C1 optimistic marks, small-sample labelling | Report fields + dashboard text + 4 tests; created these docs |
