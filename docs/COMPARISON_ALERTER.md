# Comparison with options-alerter

`elguindyyounis/options-alerter` is the owner's other project (built with ChatGPT, private, read
only for agents). It is a Mac-local FastAPI/SQLite scanner that paper-trades yfinance chains through
"lanes" and a seven-agent council. This file records what each side does differently. Update it
whenever a new alerter module is read. Platform code never imports from the alerter.

Last alerter commit reviewed: `1fc88f18f2875bb115f8264700a9835cebe45c80` (16 commits at first review).

## Modules read so far

| Alerter module | What it does | Platform comparison |
|---|---|---|
| `feedback.py` | Journals every sampled, rejected and missed setup, then marks it 1/7/30 days later at ask+slippage in, bid-slippage out. Requires the later quote to be >12h newer; unresolved cases become `NO_DATA` rather than guessed. Every outcome is labelled `quote_time_verified: False` and "indicative, never actual fills". | Platform has no counterfactual journal. It only sees trades it took, so it cannot tell whether risk rejections saved money. Candidate for a future "shadow outcomes" table (needs the quote recorder, backlog 1). |
| `core.py` | Deterministic candidate scoring, finite-number guards, RSI/EMA/SMA. | Platform strategy is simpler and has fewer inputs. Both say scores are rankings, not probabilities. |
| `liquidity.py`, `entry_quality.py` | Liquidity grading and an entry-quality assessor before admission. | Platform uses hard spread/volume/OI thresholds in the strategy and the risk engine. No graded quality label. |
| `paper_engine.py`, `risk.py` | Paper fills and broker-side gating, with defaults `max_position_pct` 8, `max_total_pct` 40, `max_drawdown_pct` 30 and a profile named "aggressive". | Platform's fail-closed `RiskPolicy` is stricter by default. Owner chose the alerter's large lane sizes; not touched. |
| `exit_decisions.py` | Hard stop/target rules keep precedence. A deterministic "shadow exit" and an optional local-Ollama exit are logged as proposals only. | Platform has fixed rules only. Shadow-exit comparison is a possible research table. |
| `storage.py` | SQLite ledger with `trade_journal` (entry reviews, exit reason, return pct), atomic admission via unique open-position index. | Platform's order store plus audit log is similar in spirit; it has no per-trade journal of the reason for entry beyond the proposal rationale. |
| `data_sources.py` | yfinance rows: unverified quote times are stamped `exchange_quote_time_verified: False`; drops bids>asks; IV outside (0,10) is nulled. | Platform fails closed unless `require_verified_quote_time` is off, and says so loudly at startup. |

## Never read yet (read at least one per run)

`agents.py` (council plumbing only skimmed), `server.py`, `adaptive.py`, `agent_lab.py`,
`daily_review.py`, `gex.py`, `intraday_strategy.py`, `strategy_lanes.py`, `sizing.py`,
`research_foundations.py`, `unusual_activity.py`, `market_clock.py`, and the `agent_skills/*`
folders. `strategy_lanes.py` and `adaptive.py` matter most for the "many lanes judged on few
trades" challenge.

## Where the alerter is more honest

* Marks every hypothetical outcome as unverified and never as a fill.
* Resolves missing later quotes as no-data rather than assuming a price.

## Where the platform is more honest or stricter

* Fills are conservative on both sides (buy at ask plus slippage, sell at bid minus slippage) and
  never invented from a missing quote.
* `OrderManager` refuses any non-PAPER adapter; unknown state rejects.
