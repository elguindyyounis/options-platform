# Five outside repositories, checked against this platform (2026-11-27)

The owner asked whether five repositories should be brought into the trading agents. Short answer: **none should be
installed as a dependency**; four contain ideas worth borrowing, listed below with where they would go. Nothing here
changes a hard rule. Items that touch order types, sizing or data sources need the owner (marked).

| Repository | What it is now | Licence | Verdict |
|---|---|---|---|
| BijectiveLabs/trading-research-agents ("TRA", PyPI `bitra`) | Crypto desk on ccxt: "a rule or a model proposes, the system decides" | MIT | Borrow ideas. Closest match to this platform's design |
| HKUDS/Vibe-Trading | Large LLM agent app: research, backtests, Options Lab, Research Lab, paper and live trading under a mandate | MIT | Borrow ideas. Too large, and has live order paths |
| openbq-org/OpenBB | Not the official project: the README points to OpenBB-finance/OpenBB (Apache-2.0) | Apache-2.0 | Do not use the openbq-org copy. The official one is optional, for a Cboe cross-check only |
| TauricResearch/TradingAgents | v1.0 (2026-11-24) is a TypeScript terminal research assistant; needs a Tauric or other LLM API key; places no trades. The older Python bull/bear debate framework lives on 0.x tags | Apache-2.0 | Owner's research tool at most, not part of the agents |
| questflowai/investorskills | 63 Markdown "investor persona" skills (Buffett, Turtles, Minervini...); no code, no options | MIT | Source of hypotheses only. Its install line points at a different GitHub user: verify before installing |

## What this platform already does that these repositories recommend

* Models never place orders; deterministic rules and a fail-closed risk gate decide (TRA's core idea; hard rule 1, `agents.py`, `risk.py`).
* Idempotent orders reconciled by our own key after a timeout, never sent twice (TRA; `broker/ibkr.py` uses `orderRef`).
* Pre-registered hypotheses, later-30% out-of-sample, bootstrap intervals, ask in / bid out (Vibe-Trading Research Lab, TRA arena; `research.py`, `EVOLUTION_PLAN.md`).
* Rank-1 against the rest of the list (S1) and a lane against SPY (SW1): the "random null" and "buy and hold" rows TRA puts beside every rule.

## Ideas to borrow

1. **Reconcile the two books (Vibe-Trading's `paper_trade_reconcile`). Done in this PR.** `python -m optplat.mirror_report --db <path>`
   pairs each simulated fill with IBKR paper's outcome. The mirror now reads back still-working IBKR orders while idle, so a
   later fill is audited (`ibkr_mirror_status`). Read-only.
2. **Exits that rest at the broker (TRA).** TRA sends the stop and target with the entry so a crash cannot leave a position
   without its exit. Here exits live in the platform process; if the Mac sleeps, IBKR paper positions have no stop.
   *Owner decision*: hard rule 1 allows only DAY limit orders to IBKR, so resting stop orders would need a new rule.
3. **Typed news judge (TRA's "Jev").** If the owner chooses a news source (backlog item 5), use TRA's pattern: one headline
   per request, closed questions only, each choice asked in both orders and dropped when the answers disagree, a check for
   text addressed to a machine, and all arithmetic done by the system. Fits the plan's rule that news is never a model input as text.
4. **Seeded random-entry null in the replay harness (TRA arena).** Add a "random candidate passing the same filters, same
   exit" row beside every exit-replay and lane result, so a rule is always shown next to chance.
5. **Cost gate before entry (TRA).** Refuse a trade whose measured edge does not clear its round-trip cost. Not usable until a
   hypothesis passes and an edge is measured; *owner decision* when it is (it is a risk-policy change).
6. **Multi-leg payoffs (Vibe-Trading Options Lab).** If the plan's fallback (defined-risk spreads) is reached, its payoff and
   scenario-grid code (MIT) is a reference. Multi-leg stays out of scope until then.
7. **Cboe chains as a free second source (official OpenBB, `openbb-cboe`, no key).** Could cross-check Yahoo/IBKR quotes in
   `dataquality.py`. Delayed, and its terms of use would need checking; adding OpenBB is a heavy dependency, so a small direct
   reader would be preferred. *Owner decision* (new data source).
8. **Hypotheses from investorskills, registered before use.** For the swing lane's missing "reason to buy" (UX follow-up):
   relative strength (O'Neil), volatility contraction (Minervini), Darvas box. Turtle ATR sizing and "portfolio heat" would be
   a sizing change: *owner decision*.

## What not to do

* Do not put an LLM persona (investorskills, TradingAgents) in the order path or let it vote in the committee: it would be an
  unvalidated signal (`VALIDATED_SIGNALS` is empty on purpose) and breaks "language models never place orders".
* Do not install Vibe-Trading or TRA beside the platform: both have live-order code paths, and hard rule 1 forbids hinting at one.
* Do not install anything from openbq-org; use OpenBB-finance only.
