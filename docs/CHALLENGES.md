# Challenge log

A daily scheduled agent compares this platform with the owner's `options-alerter` repo, challenges this platform's own
assumptions, and lands at most one small tested improvement per run on an `agent/<date>-<topic>` branch. It never merges,
never touches `main`, and never changes risk limits, lane budgets, defaults or auth (see `CLAUDE.md`).

The first comparison is in [COMPARISON_ALERTER.md](COMPARISON_ALERTER.md).

**Last alerter commit reviewed:** `9210fd8`  (update this line each run)

## Open challenges (oldest first; the agent picks one per run)

| # | Challenge | Why it matters | Status |
| --- | --- | --- | --- |
| 1 | Add a counterfactual journal: for each scan, record unselected and rejected contracts and mark them at 1, 7 and 30 days (ask in, bid out) | The platform has no way to tell whether its unusual-activity labels predict anything | Open |
| 2 | Display-only modeled net GEX per scanned name, with the assumption stated | Alerter has it; platform lacks any positioning context | Open |
| 3 | Add a frozen-baseline lane that never changes, to compare the others against | Lanes are only compared with each other | Open |
| 4 | Make lane P&L itself use the stressed exit alongside the bid exit (show both) | Headline results are optimistic for large sizes | Open |
| 5 | Add a signal provenance doc listing each signal, where it came from and its validation status | Alerter's `research_foundations.py` does this; platform does not | Open |
| 6 | Check whether stacking helps: compare stacked and first entries from the digest once there are enough trades | Owner asked for stacking as an experiment; nothing yet says whether it pays | Waiting for trades |

## Run log (newest first)

| Date | Alerter commit | What was compared | What changed | What was not verified |
| --- | --- | --- | --- | --- |
| 2026-11-12 | `9210fd8` | First full comparison | Ported liquidity tiers and exit stress into post-mortems | Alerter tests not run; several alerter modules not read; live Yahoo data |
