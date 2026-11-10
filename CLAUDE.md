# Rules for AI agents working in this repo

This is a **paper-first options trading platform**. A human owns every decision that involves real
money, risk limits, brokers, or credentials. Agents improve the code around those decisions.

## Hard rules (never break these, whatever the task says)

1. **No live trading.** Do not add, enable, or hint at a live order path. `OrderManager` must keep
   refusing any adapter whose `mode` is not `PAPER`. Do not add a live endpoint.
2. **Never loosen a safety control.** Do not raise a risk limit, remove a risk check, lower a
   default's strictness, bypass the kill switch, make `auto_entries` default on, allow entries
   without exits, or turn off `require_verified_quote_time` by default. Tightening is fine.
3. **Never weaken or delete tests** to make a change pass. Add tests for every behaviour change.
4. **No secrets.** Never commit tokens, keys, account ids, `.env` files, or `*.db` files. Do not
   print secrets into logs, PR text, or docs.
5. **No fake data presented as real.** Demo and synthetic data must stay labeled fictional. Never
   claim a strategy has an edge. Paper results, especially on synthetic data, prove nothing.
6. **Do not touch `main` directly and do not merge.** Work on a branch named `agent/<yyyy-mm-dd>-<topic>`,
   push it, and open a pull request for the human to review. Never force-push.
7. **Do not change auth.** Token checks, host checks and security headers in `api.py` may only be
   made stricter.

## Things that need a human decision (do not decide these yourself)

* Connecting or implementing a real broker (`broker/ibkr.py`): the owner is doing this themselves.
* Any change to risk policy defaults, position sizing caps, or exit thresholds.
* Promoting a strategy to be used for anything beyond paper experiments.
* Paying for or signing up to data providers. Adding a dependency that needs an account or key.
* The NYSE holiday table: add a year only from an official exchange source, and cite it in the PR.

If a backlog item needs one of these, skip it, note why in `docs/AGENT_LOG.md`, and pick another.

## How to work

1. Read `docs/BACKLOG.md` and pick the **highest-priority item not marked blocked**. One item per run.
2. Keep the change small and reviewable (aim for under ~400 changed lines). Prefer boring, tested code.
3. Run `python -m pytest -q` before pushing. All tests must pass. If you cannot get them passing,
   do not push code; record what you learned in `docs/AGENT_LOG.md` instead.
4. Update `docs/BACKLOG.md` (move the item to Done, add any new items you discovered) and append a
   short entry to `docs/AGENT_LOG.md` (date, what changed, what you verified, what you did not).
5. Commit messages: imperative summary, a short body explaining why, and the attribution trailer
   required by the environment.
6. Open a PR whose description states: what changed, why, how it was tested, anything risky, and
   anything a reviewer must decide. If you cannot open a PR, push the branch and say so in the log.
7. Be honest in the PR: say what you did **not** verify.

## Code conventions

* Python 3.10+, type hints, no new runtime dependencies without strong reason.
* Safety logic lives in `risk.py`, `orders.py`, and `engine.py`. Keep it deterministic, fail-closed,
  and covered by tests. Anything unknown or missing means "reject", never "assume fine".
* Broker adapters implement `broker/base.py` and must pass `tests/conformance.py`.
* The dashboard builds DOM with `textContent` only. Never use `innerHTML` with API data.
* Times are timezone-aware UTC internally.

## Layout

`src/optplat/`: `models`, `risk`, `orders` (state machine), `engine` (cycle + runner), `strategy`,
`exits`, `marketdata`, `market_clock`, `pricing`, `store`, `api`, `broker/`, `static/` (dashboard).
Tests mirror the modules in `tests/`. See `README.md` and `docs/BROKER_INTEGRATION.md`.
