# Challenge log

A daily scheduled agent compares this platform with the owner's `options-alerter` repo, challenges this platform's own
assumptions, and lands at most one small tested improvement per run on an `agent/<date>-<topic>` branch. It never merges,
never touches `main`, and never changes risk limits, lane budgets, defaults or auth (see `CLAUDE.md`).

The first comparison is in [COMPARISON_ALERTER.md](COMPARISON_ALERTER.md).

**Last alerter commit reviewed:** `1fc88f1`  (update this line each run)

## Open challenges (oldest first; the agent picks one per run)

| # | Challenge | Why it matters | Status |
| --- | --- | --- | --- |
| A | **Simulated account forgets its positions on restart.** `SimBroker` keeps positions in memory. The live DB shows one SPY put filled on 2026-11-11 (no sell order), then equity reset to exactly 100,000 with no position after a restart on 2026-11-12. Rebuild positions from FILLED orders at startup (fail closed if they do not reconcile) and show a warning when equity was reset. | A reset hides a real paper loss and makes the headline number look flat | Done 2026-11-13 (`SimBroker.restore`); pull and restart to get the lost SPY put back |
| B | **Scan errors hide their cause.** One chain per scan fails with `AttributeError` and the message is dropped. Log the exception text and the failing line. | Cannot fix what cannot be seen | Done 2026-11-13 (`describe_exc`: message and file:line). Check the next scan for the real NVDA cause |
| C | **Show clock skew loudly.** The Mac clock runs 7 to 11 s behind quote timestamps; the data-quality gate allows 5 s, so 29 of 30 scan chains and nearly every SPY/QQQ entry were rejected (FUTURE_TIMESTAMP, 496 rejects since 2026-11-11). Measure the skew from quote timestamps and show "your clock is N s behind" on the dashboard. **Do not raise the 5 s tolerance: that is the owner's call.** The owner can sync the Mac clock instead. | The flow lane, scanner and real account are all starved by this | Display done 2026-11-13 (Controls trust panel and status). Tolerance and the Mac clock fix need the owner |
| D | **Challenge the 10x account's critic.** Once `challenge:history` has several finished attempts, compare what the critic vetoed with what it let through, which objections preceded the worst trades, and whether any attempt reached 10x by luck of one big trade. Propose rule changes only as tightening or as new tests; never judge an attempt on its best trade. | The challenge only teaches something if the critic is itself tested | Waiting for attempts |
| 1 | Add a counterfactual journal: for each scan, record unselected and rejected contracts and mark them at 1, 7 and 30 days (ask in, bid out) | The platform has no way to tell whether its unusual-activity labels predict anything | Open |
| 2 | Display-only modeled net GEX per scanned name, with the assumption stated | Alerter has it; platform lacks any positioning context | Open |
| 3 | Add a frozen-baseline lane that never changes, to compare the others against | Lanes are only compared with each other | Done 2026-11-13 (`frozen-baseline-options`, pinned by a fingerprint test). Comparing the lanes against it still needs enough trades |
| 4 | Make lane P&L itself use the stressed exit alongside the bid exit (show both) | Headline results are optimistic for large sizes | Open |
| 5 | Add a signal provenance doc listing each signal, where it came from and its validation status | Alerter's `research_foundations.py` does this; platform does not | Done 2026-11-14 ([SIGNALS.md](SIGNALS.md), with a drift test that fails if a signal or cause tag is undocumented or its status disagrees with `VALIDATED_SIGNALS`) |
| 7 | **Open positions were marked at any valid bid.** The alerter refuses a mark on a quote over 30 min old or a spread over 35%. | A stale or very wide bid made open P&L look like a number it was not | Done 2026-11-14 (`marks.py`, used by the trades table and the report; tightening only, display only) |
| 8 | **Volume/OI looks bigger than it is on a tiny OI.** The alerter caps a contract's score when OI < 20 or volume < 5, because a small denominator inflates the ratio. The platform's scanner score even adds +15 for low OI (a deliberate "fresh position" signal, and an existing test pins it). | A 150-lot on OI of 5 reads as 30x and ranks first, yet that ratio is mostly the denominator | Done 2026-11-14 (display-only `ratio_basis` tag; score unchanged). Whether to cap the score the way the alerter does is the owner's call, since it would change scan ranking and a pinned test |
| 6 | Check whether stacking helps: compare stacked and first entries from the digest once there are enough trades | Owner asked for stacking as an experiment; nothing yet says whether it pays | Waiting for trades |

## Run log (newest first)

| Date | Alerter commit | What was compared | What changed | What was not verified |
| --- | --- | --- | --- | --- |
| 2026-11-14 (c) | `1fc88f1` | Alerter unchanged. Read `agents.py` and `core.py`: the optional local-model council can only make a verdict stricter (cannot upgrade a rejection), sends only an allow-listed field set to a localhost-only endpoint, labels headlines untrusted. `candidate_score` caps scores for vol < 5, OI < 20, spread > 20% and no volume/ask | `ratio_basis` display tag on scanner unusual rows plus a test | Alerter tests not run; `server.py` unread; sibling `agent/2026-11-14-*` branches not merged into this one; live data |
| 2026-11-14 (b) | `1fc88f1` | Alerter unchanged since last review. Read `research_foundations.py` signal table in full and `data_sources.py` (`option_rows`: drops quotes with bid>ask, nulls IV outside 0 to 10, marks `exchange_quote_time_verified: False`, `trade_level_flow: False`, `is_demo` per row) | `docs/SIGNALS.md` provenance doc plus `tests/test_signal_provenance.py` | Alerter tests not run; `agents.py`, `core.py`, `server.py` still unread; live data; sibling `agent/2026-11-14-*` branches are not merged into this one, so overlapping items (lane stress P&L, GEX display, fill tags, sample gates) may already exist elsewhere |
| 2026-11-14 | `1fc88f1` | Alerter changed CI only. Read `storage.py` (mark and fill rules) | Open-position marks now need a quote under 30 min old and a spread of at most 35% (`marks.py`) | Alerter tests not run; `agents.py`, `core.py` (partly), `server.py`, `data_sources.py` still not fully read; live data; this branch was cut from `agent/integration` because `main` lacks these docs |
| 2026-11-12 | `9210fd8` | First full comparison | Ported liquidity tiers and exit stress into post-mortems | Alerter tests not run; several alerter modules not read; live Yahoo data |
