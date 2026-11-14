# Challenge log

A daily scheduled agent compares this platform with the owner's `options-alerter` repo, challenges this platform's own
assumptions, and lands at most one small tested improvement per run on an `agent/<date>-<topic>` branch. It never merges,
never touches `main`, and never changes risk limits, lane budgets, defaults or auth (see `CLAUDE.md`).

The first comparison is in [COMPARISON_ALERTER.md](COMPARISON_ALERTER.md).

**Last alerter commit reviewed:** `9210fd8`  (update this line each run)

## Open challenges (oldest first; the agent picks one per run)

| # | Challenge | Why it matters | Status |
| --- | --- | --- | --- |
| A | **Simulated account forgets its positions on restart.** `SimBroker` keeps positions in memory. The live DB shows one SPY put filled on 2026-11-11 (no sell order), then equity reset to exactly 100,000 with no position after a restart on 2026-11-12. Rebuild positions from FILLED orders at startup (fail closed if they do not reconcile) and show a warning when equity was reset. | A reset hides a real paper loss and makes the headline number look flat | Done 2026-11-13 (`SimBroker.restore`); pull and restart to get the lost SPY put back |
| B | **Scan errors hide their cause.** One chain per scan fails with `AttributeError` and the message is dropped. Log the exception text and the failing line. | Cannot fix what cannot be seen | Done 2026-11-13 (`describe_exc`: message and file:line). Check the next scan for the real NVDA cause |
| C | **Show clock skew loudly.** The Mac clock runs 7 to 11 s behind quote timestamps; the data-quality gate allows 5 s, so 29 of 30 scan chains and nearly every SPY/QQQ entry were rejected (FUTURE_TIMESTAMP, 496 rejects since 2026-11-11). Measure the skew from quote timestamps and show "your clock is N s behind" on the dashboard. **Do not raise the 5 s tolerance: that is the owner's call.** The owner can sync the Mac clock instead. | The flow lane, scanner and real account are all starved by this | Display done 2026-11-13 (Controls trust panel and status). Tolerance and the Mac clock fix need the owner |
| D | **Challenge the 10x account's critic.** Once `challenge:history` has several finished attempts, compare what the critic vetoed with what it let through, which objections preceded the worst trades, and whether any attempt reached 10x by luck of one big trade. Propose rule changes only as tightening or as new tests; never judge an attempt on its best trade. | The challenge only teaches something if the critic is itself tested | Waiting for attempts |
| 1 | Add a counterfactual journal: for each scan, record unselected and rejected contracts and mark them at 1, 7 and 30 days (ask in, bid out) | The platform has no way to tell whether its unusual-activity labels predict anything | Partly done 2026-11-13: `tracker.py` marks every flagged contract at 1, 3 and 7 trading days. Still open: contracts the scan did not flag, and 30 day marks |
| 2 | Display-only modeled net GEX per scanned name, with the assumption stated | Alerter has it; platform lacks any positioning context | Done 2026-11-14 (upgrade of `signals.gex`: gross, both sign conventions, zero-gamma spot, skip reasons). Not validated; needs 30+ trading days of snapshots and the counterfactual journal before it can mean anything |
| 3 | Add a frozen-baseline lane that never changes, to compare the others against | Lanes are only compared with each other | Open |
| 4 | Make lane P&L itself use the stressed exit alongside the bid exit (show both) | Headline results are optimistic for large sizes | Done 2026-11-13: option lane summary has `stress_pnl` beside `stress_bid_pnl` over the same trades, shown as "Realized, harder exit". The headline `realized_pnl` is unchanged. Not yet on the 10x challenge panel or the All trades sources table |
| 5 | Add a signal provenance doc listing each signal, where it came from and its validation status | Alerter's `research_foundations.py` does this; platform does not | Open |
| 6 | Check whether stacking helps: compare stacked and first entries from the digest once there are enough trades | Owner asked for stacking as an experiment; nothing yet says whether it pays | Waiting for trades |
| 7 | Do tiny open interest dominate the volume/OI ratio that flags a contract as unusual? The alerter caps scores for volume < 5, OI < 20 and spread > 20%. Add a tracker group split by OI size and compare marks | A ratio over a tiny denominator is easy to hit and may be noise | Done 2026-11-13: tracker feature `oi_size`. Needs real marks before it says anything |

## Run log (newest first)

| Date | Alerter commit | What was compared | What changed | What was not verified |
| --- | --- | --- | --- | --- |
| 2026-11-13 (later) | `9210fd8` (no change) | Read `storage.py` and `data_sources.py` | Challenge 7: tracker `oi_size` split (display-only) | Alerter tests not run; no real marks seen; dashboard not checked in a browser |
| 2026-11-13 | `9210fd8` (no change) | Read `agents.py` and `core.py` | Challenge 4: lane summary shows bid and stressed realized P&L side by side (display-only) | Alerter tests not run; the stressed number is a model, not a fill; no real trades seen; dashboard tile not checked in a browser |
| 2026-11-12 | `9210fd8` | First full comparison | Ported liquidity tiers and exit stress into post-mortems | Alerter tests not run; several alerter modules not read; live Yahoo data |
