# Comparison with options-alerter (read-only, built by ChatGPT)

Only modules actually read are listed. Never read yet: `agents.py`, `core.py`, `storage.py`,
`server.py`, `data_sources.py`, `agent_skills/*`, and everything else not named below.

## Read on 2026-11-15 (alerter at 48ccf71)

**`liquidity.py`.** Scores volume, open interest, spread and premium turnover, then labels each
contract PREFERRED / WATCH / THIN with plain reasons (for example "N contracts exceeds 10% of
reported OI"). `exit_stress` models bid liquidation under three concession levels (base, thin
market, stressed) so a result can be read under worse exits. It says outright that OI and volume
are not live depth. The platform has a single flat slippage in `broker/sim.py` and no liquidity or
size-versus-volume check. See challenge C2 in `CHALLENGES.md`.

**`strategy_performance.py`.** Per-lane closed-trade summary with profit factor, closed-trade-only
drawdown (explicitly labelled as not account drawdown), win rate that is null rather than 0% with
no trades, and a `limitations` string on every block. Competitor comparison is refused as a
"winner" claim because imported trades are unverified. The platform's `/api/report` used to show a
bare win rate and total; challenge C1 (done) borrows the alerter's approach.

## Not yet compared

Strategy lane logic (`strategy_lanes.py`, `lane_paper_engine.py`), `risk.py`, `sizing.py`,
`entry_quality.py`, GEX/FVG modules, the shadow runner and the Mac deployment scripts.
