# Signal provenance

Every signal, rule or label this platform uses, where it came from, and whether any evidence supports it.
This is the platform's version of the alerter's `research_foundations.py`. `tests/test_signal_docs.py` fails if a signal,
lane or committee agent is added in code without a row here, so the doc cannot silently go stale.

**Validation status values**

* `UNVALIDATED`: no evidence of predictive value. The default for everything.
* `MODEL_ASSUMPTION`: a standard formula whose inputs here are assumptions (rate, dealer sign), not market facts.
* `INFERENCE`: a label guessed from delayed free data (for example buy/sell from the last print). A hint, not a fact.
* `RISK_RULE`: a safety or friction rule that exists to limit loss, not to predict anything.

Nothing in this file is `VALIDATED`. `signals.VALIDATED_SIGNALS` is empty and only the owner may change it, after
`study_signal` and a pre-registered experiment. Paper results on the free delayed feed prove nothing about an edge.

## Signals in `signals.py` (`SIGNAL_NAMES`)

| Signal | Origin | Status | Caveat |
| --- | --- | --- | --- |
| `call_put_volume_ratio` | Common heuristic | UNVALIDATED | Volume is a running daily total with no aggressor side |
| `call_put_oi_ratio` | Common heuristic | UNVALIDATED | Open interest updates once a day |
| `unusual_count` | Developer heuristic (volume >= 100, OI >= 50, volume/OI >= 1) | UNVALIDATED | A small open interest makes the ratio easy to hit; see tracker feature `oi_size` |
| `gex_total` | Black-Scholes gamma plus a dealer-sign convention | MODEL_ASSUMPTION, UNVALIDATED | Needs an assumption about who holds what; the net figure flips sign with the convention. Chain is a sample. Published evidence concerns index/futures into the close, not single names |

## Lane entry rules (`optionlanes.py`)

| Lane id | Rule | Origin | Status |
| --- | --- | --- | --- |
| `shortterm-options-base` | 9-period EMA crosses the session VWAP | Textbook indicator pair | UNVALIDATED |
| `shortterm-options-aggr` | Same signal, more names, closer expiry, larger size, stacking | Owner's choice of experiment | UNVALIDATED |
| `swing-options-base` | Trend (fast above slow average) with an RSI dip and a turn up | Textbook pullback rule | UNVALIDATED |
| `swing-options-aggr` | Looser pullback, puts on a bounce in a downtrend, stacking | Owner's choice of experiment | UNVALIDATED |
| `flow-options` | Flagged contract with very high volume/OI whose OI rose the next day | Developer heuristic | UNVALIDATED; the tracker is the intended test |
| `frozen-baseline-options` | A fixed copy of the first short-term rule, pinned by a fingerprint | Yardstick, not a strategy | UNVALIDATED; it exists so other lanes have something to be compared with |

## Committee agents (`agents.py`)

| Agent | Basis | Status |
| --- | --- | --- |
| `technical` | Moving averages and RSI on daily closes | UNVALIDATED |
| `volatility` | Realized volatility of daily closes | UNVALIDATED |
| `sentiment` | Sector and market breadth from the scan universe | UNVALIDATED; starts at reduced weight |
| `flow` | Flagged unusual activity on the same name; it can only argue against a trade | INFERENCE, UNVALIDATED; starts at reduced weight |
| `execution` | Spread and liquidity of the contract | RISK_RULE |
| `exposure` | Concentration against open positions | RISK_RULE |
| `events` | Earnings and FOMC dates (Yahoo calendar is unofficial) | RISK_RULE |
| `skeptic` | Objections to the candidate; can veto | RISK_RULE |

Committee weights are learned from outcomes (`committee.fit`, shrunk, capped, newest 500 decisions). That is a learning rule,
not evidence that any agent predicts anything.

## Labels inferred from free data

| Label | How it is inferred | Status |
| --- | --- | --- |
| Buy or sell side (`likely_side`) | Last print compared with bid and ask | INFERENCE |
| Opening or closing (`oi_verdict`) | Next day's open interest against the prior day's | INFERENCE |
| Bullish or bearish lean | Side and right (a bought call or sold put is bullish) | INFERENCE on top of INFERENCE |
| Liquidity tier and stressed exit (`liquidity.py`) | Ported from the alerter: thresholds on spread, volume, open interest and size | RISK_RULE with developer-chosen numbers |

## Where the alerter differs

The alerter's `research_foundations.py` also cites overfitting papers (Novy-Marx, NBER 2015; Bailey et al., 2017) beside its
signals and states that its score weights are developer-chosen and not fit to data. The platform has the same limitation
(lane parameters and committee thresholds are developer-chosen) and reports it through sample-size labels and the
best-of-N caveat on the lane comparison, but did not previously list sources per signal. This file is the first step.
Adding references for a signal is welcome, but a reference for a mechanism is not validation of the rule built on it.
