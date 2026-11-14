# Signal provenance

Every signal or entry rule the platform uses, where it came from, and what evidence exists for it. Modelled on the alerter's
`research_foundations.py`. **Nothing here is validated.** "Validated" would mean an owner-reviewed forward study with enough
independent trades; none exists, and paper results on delayed free data do not provide one. This page is a checklist of
hypotheses, not a list of edges.

`tests/test_signal_provenance.py` keeps this page honest: every name in `signals.SIGNAL_NAMES` and every lane in
`optionlanes.ALL_PARAMS` must appear below, and a signal's status here must match `signals.VALIDATED_SIGNALS`.
Statuses: `UNVALIDATED` (no study), `STUDY_ONLY` (measured by `study_signal`, not pre-registered), `VALIDATED` (owner added it
to `VALIDATED_SIGNALS`).

## Research signals (`signals.py`, display and study only; `use_signal` blocks strategies)

| Signal | Definition | Origin | Status | Main caveat |
| --- | --- | --- | --- | --- |
| `call_put_volume_ratio` | Day's call volume over put volume in the sampled chain | Common market heuristic | UNVALIDATED | The chain is a sample; volume is a running total; says nothing about who initiated |
| `call_put_oi_ratio` | Call open interest over put open interest | Common market heuristic | UNVALIDATED | OI is the prior day's figure; hedgers and spreads are mixed in |
| `unusual_count` | Contracts with volume at least 100, OI at least 50 and volume/OI at least 1 | Developer threshold | UNVALIDATED | Thresholds were chosen by hand, not fitted; "unusual" is relative to OI only |
| `gex_total` | Modelled net gamma exposure, Black-Scholes, rate 0 | Standard model plus a contested dealer-positioning assumption | UNVALIDATED | Partial chain; customers-long-calls assumption is stated in each result and may be wrong |

## Inferred labels (`scanner.py`, shown on the dashboard, used by the flow lane)

| Label | How it is inferred | Status | Main caveat |
| --- | --- | --- | --- |
| Buy or sell side | Last print against the bid and ask | UNVALIDATED | One delayed print; a print at the ask can be a seller's lift or a spread leg |
| `BUY_TO_OPEN` / `SELL_TO_OPEN` | Open interest change between sightings | UNVALIDATED | Needs exact side; `oi_sessions` and `oi_window_clean` say how many sessions the change spans. Only one session is clean |
| `lean` (BULLISH / BEARISH) | Position read combined with call or put | UNVALIDATED | Two stacked inferences. Treat as a hint, never as fact |

## Lane entry rules (`optionlanes.py`)

These are experiments the owner asked for. Their parameters were set by hand, so any good-looking result may be selection luck;
judge them only against `frozen-baseline-options` and only with a sample large enough to mean something.

| Lane id | Entry idea | Origin | Status | Main caveat |
| --- | --- | --- | --- | --- |
| `shortterm-options-base` | EMA9 crossing the session VWAP | Common technical rule | UNVALIDATED | Single-leg weekly options; costs and wide exits can swamp small moves |
| `shortterm-options-aggr` | Same signal, more names, shorter expiry, bigger size, stacking | Variation of the above | UNVALIDATED | Several settings changed at once, so a result cannot say which one mattered |
| `swing-options-base` | Pullback inside an uptrend, as a call 30 to 60 days out | Common technical rule | UNVALIDATED | Few signals per year, so samples stay small for months |
| `swing-options-aggr` | Looser pullback rule, puts on a bounce in a downtrend | Variation of the above | UNVALIDATED | Same multiple-changes problem |
| `flow-options` | High volume/OI and next-day OI rise, then trade the inferred lean | Alerter-style unusual-activity idea | UNVALIDATED | Rests on the inferred labels above; free delayed data |
| `frozen-baseline-options` | A frozen copy of the first short-term rule | Yardstick, pinned by `FROZEN_FINGERPRINT` | UNVALIDATED | A reference for comparison, not a recommendation |

## What would change a status

1. Record the hypothesis and the horizon before looking at results (`research.py` pre-registration).
2. Collect enough independent observations (overlapping ones count as one), on data the strategy was not tuned on.
3. Compare with the frozen baseline and with a do-nothing rule, after costs and a stressed exit.
4. The owner decides. An agent never moves a signal to `VALIDATED`.

## References the alerter cites (not checked by this repo)

* Novy-Marx, *Backtesting Strategies Based on Multiple Signals* (NBER 2015): many signal combinations tried on one history overfit.
* Bailey et al., *The Probability of Backtest Overfitting* (2017): selection among many variants inflates the best result.
