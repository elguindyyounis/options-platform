"""Pre-registered strategy experiments: a challenger against a frozen baseline.

The rules that keep this honest, all enforced in code:

* The baseline is frozen. Its parameters are fingerprinted; if they ever change, evaluation refuses to run
  and a new baseline version must be created on purpose.
* A hypothesis (statement, challenger, pass criteria) is written down before any result exists. It is stored
  append-only with a content hash. There is no way to edit or delete it. A change is a new hypothesis.
* Pass criteria cannot be laxer than the evaluation module's minimum trade counts.
* A *confirmatory* evaluation uses only snapshots recorded after the hypothesis was registered, so it cannot be
  fitted to data already seen. Looking at older data is *exploratory* and can never pass.
* The first time the sample requirements are met, the verdict is recorded and final. Re-running returns the same
  verdict instead of checking again until one comes out right.
* "Passed" means the pre-registered bar was met on this sample. It is not proof of an edge, and promoting a
  strategy to anything beyond paper experiments is the owner's decision.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from .evaluation import MIN_OOS_TRADES, MIN_TRADES, evaluate
from .models import utcnow
from .risk import RiskPolicy
from .store import Store
from .strategy import LiquidTrendStrategy, Strategy

STRATEGIES = {"liquid-trend": LiquidTrendStrategy}
METRICS = ("expectancy_per_trade", "realized_pnl", "return_pct")
FINAL = ("PASSED_CRITERIA", "FAILED_CRITERIA")


@dataclass(frozen=True)
class StrategySpec:
    name: str
    version: str
    params: tuple[tuple[str, float], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StrategySpec":
        if d.get("name") not in STRATEGIES:
            raise ValueError(f"Unknown strategy {d.get('name')!r}; known: {sorted(STRATEGIES)}")
        version = str(d.get("version", "")).strip()
        if not version or len(version) > 40:
            raise ValueError("version is required (at most 40 characters)")
        allowed = set(inspect.signature(STRATEGIES[d["name"]].__init__).parameters) - {"self"}
        params = d.get("params") or {}
        for k, v in params.items():
            if k not in allowed:
                raise ValueError(f"Unknown parameter {k!r}; allowed: {sorted(allowed)}")
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"Parameter {k!r} must be a number")
        return cls(d["name"], version, tuple(sorted((k, float(v) if isinstance(v, float) else v) for k, v in params.items())))


def build_strategy(spec: StrategySpec) -> Strategy:
    strat = STRATEGIES[spec.name](**dict(spec.params))
    strat.version = spec.version
    return strat


def fingerprint(spec: StrategySpec) -> str:
    """Hash of the strategy's class, resolved parameters (defaults included) and version."""
    cls = STRATEGIES[spec.name]
    resolved = {k: p.default for k, p in inspect.signature(cls.__init__).parameters.items() if k != "self"}
    resolved.update(dict(spec.params))
    blob = json.dumps({"name": spec.name, "version": spec.version, "params": resolved}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def params_fingerprint(spec: StrategySpec) -> str:
    """Like `fingerprint` but ignoring the version label, to tell whether two specs behave identically."""
    return fingerprint(StrategySpec(spec.name, "-", spec.params))


BASELINE = StrategySpec("liquid-trend", "0.1.0")
# Changing this value, or LiquidTrendStrategy's defaults, means the baseline moved. Do it on purpose, as a new version.
BASELINE_FINGERPRINT = "8df80d6165f1bcd195d18b76210943f42aa245d95e0039b988f3116bdac04353"


def baseline_is_frozen() -> bool:
    return fingerprint(BASELINE) == BASELINE_FINGERPRINT


def validate_criteria(c: dict[str, Any]) -> dict[str, Any]:
    out = {
        "metric": c.get("metric", "expectancy_per_trade"),
        "min_improvement": c.get("min_improvement"),
        "min_trades": int(c.get("min_trades", MIN_TRADES)),
        "min_oos_trades": int(c.get("min_oos_trades", MIN_OOS_TRADES)),
        "max_drawdown_worsening_pct": float(c.get("max_drawdown_worsening_pct", 0.0)),
    }
    if out["metric"] not in METRICS:
        raise ValueError(f"metric must be one of {METRICS}")
    if not isinstance(out["min_improvement"], (int, float)) or isinstance(out["min_improvement"], bool) or out["min_improvement"] <= 0:
        raise ValueError("min_improvement is required and must be a number > 0 (a tie is not an improvement)")
    if out["min_trades"] < MIN_TRADES or out["min_oos_trades"] < MIN_OOS_TRADES:
        raise ValueError(f"Criteria cannot be laxer than the minimums ({MIN_TRADES} trades, {MIN_OOS_TRADES} out of sample)")
    if not 0 <= out["max_drawdown_worsening_pct"] <= 5:
        raise ValueError("max_drawdown_worsening_pct must be between 0 and 5")
    return out


def _canonical(payload: dict[str, Any], registered_at: str) -> str:
    return hashlib.sha256(json.dumps({**payload, "registered_at": registered_at}, sort_keys=True).encode()).hexdigest()


def register(store: Store, statement: str, challenger: dict[str, Any], criteria: dict[str, Any],
             now: Optional[datetime] = None) -> str:
    if not statement.strip() or len(statement) > 1000:
        raise ValueError("A hypothesis needs a statement (up to 1000 characters)")
    if not baseline_is_frozen():
        raise RuntimeError("The baseline strategy has changed; refusing to register against a moving baseline")
    spec = StrategySpec.from_dict(challenger)
    if params_fingerprint(spec) == params_fingerprint(BASELINE):
        raise ValueError("The challenger behaves identically to the baseline")
    now = now or utcnow()
    payload = {
        "statement": statement.strip(),
        "challenger": spec.to_dict(),
        "baseline": BASELINE.to_dict(),
        "baseline_fingerprint": BASELINE_FINGERPRINT,
        "criteria": validate_criteria(criteria),
    }
    return store.register_hypothesis(now, _canonical(payload, now.isoformat()), payload)


def verify(h: dict[str, Any]) -> bool:
    body = {k: v for k, v in h["payload"].items() if k != "id"}
    return _canonical(body, h["registered_at"]) == h["content_hash"]


def evaluate_hypothesis(
    store: Store, hid: str, mode: str = "confirmatory", policy: Optional[RiskPolicy] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    if mode not in ("confirmatory", "exploratory"):
        raise ValueError("mode must be confirmatory or exploratory")
    now = now or utcnow()
    h = store.get_hypothesis(hid)
    if h is None:
        raise KeyError(hid)
    if not verify(h):
        raise RuntimeError(f"{hid} does not match its recorded hash: it was altered after registration")
    if not baseline_is_frozen():
        raise RuntimeError("The baseline strategy has changed; refusing to evaluate against a moving baseline")
    prior = [r for r in store.hypothesis_results(hid) if r["status"] in FINAL and r["mode"] == "confirmatory"]
    if mode == "confirmatory" and prior:
        return {**prior[0]["payload"], "already_final": True}

    p = h["payload"]
    crit = p["criteria"]
    reg_at = datetime.fromisoformat(h["registered_at"])
    rows = store.list_snapshots(since=reg_at if mode == "confirmatory" else None, limit=100_000)
    if mode == "confirmatory":
        rows = [r for r in rows if datetime.fromisoformat(r["recorded_at"]) > reg_at]  # strictly after registration
    base: dict[str, Any] = {
        "hypothesis": hid, "statement": p["statement"], "mode": mode, "criteria": crit,
        "registered_at": h["registered_at"], "snapshots_used": len(rows),
        "hypotheses_registered": len(store.list_hypotheses()),
        "caveats": [
            "PASSED_CRITERIA means the pre-registered bar was met on this sample. It is not proof of an edge.",
            "The more hypotheses are tried, the more likely one passes by luck. The count registered is shown above.",
            "Simulated fills on delayed, unofficial data; one market regime. Promotion is the owner's decision.",
        ],
    }
    try:
        cfg = {"auto_entries": True}
        challenger = evaluate(rows, strategy=build_strategy(StrategySpec.from_dict(p["challenger"])), config=cfg,
                              policy=policy, min_trades=crit["min_trades"], min_oos_trades=crit["min_oos_trades"])
        baseline = evaluate(rows, strategy=build_strategy(BASELINE), config=cfg, policy=policy,
                            min_trades=crit["min_trades"], min_oos_trades=crit["min_oos_trades"])
    except ValueError as exc:  # too little data to split, or none at all
        result = {**base, "status": "INSUFFICIENT_DATA", "reasons": [str(exc)]}
        store.record_hypothesis_result(hid, now, mode, "INSUFFICIENT_DATA", result)
        return result

    c_is, c_oos = challenger["segments"]
    b_is, b_oos = baseline["segments"]
    base.update(challenger={"in_sample": c_is, "out_of_sample": c_oos}, baseline={"in_sample": b_is, "out_of_sample": b_oos})
    reasons = []
    tot_c = c_is["closed_trades"] + c_oos["closed_trades"]
    tot_b = b_is["closed_trades"] + b_oos["closed_trades"]
    if min(tot_c, tot_b) < crit["min_trades"]:
        reasons.append(f"closed trades in total: challenger {tot_c}, baseline {tot_b}; need {crit['min_trades']} each")
    if min(c_oos["closed_trades"], b_oos["closed_trades"]) < crit["min_oos_trades"]:
        reasons.append(f"closed trades out of sample: challenger {c_oos['closed_trades']}, baseline {b_oos['closed_trades']};"
                       f" need {crit['min_oos_trades']} each")
    m = crit["metric"]
    if not reasons and any(x[m] is None for x in (c_is, c_oos, b_is, b_oos)):
        reasons.append(f"{m} is undefined in a segment")
    if reasons:
        status = "INSUFFICIENT_DATA"
    elif mode == "exploratory":
        status, reasons = "EXPLORATORY_ONLY", ["Exploratory runs use data seen before registration and can never pass"]
    else:
        better_oos = c_oos[m] >= b_oos[m] + crit["min_improvement"]
        consistent = c_is[m] >= b_is[m]
        drawdown_ok = c_oos["max_drawdown_pct"] <= b_oos["max_drawdown_pct"] + crit["max_drawdown_worsening_pct"]
        status = "PASSED_CRITERIA" if (better_oos and consistent and drawdown_ok) else "FAILED_CRITERIA"
        reasons = [f"out-of-sample {m} improvement met: {better_oos}", f"in-sample not worse: {consistent}",
                   f"out-of-sample drawdown within allowance: {drawdown_ok}"]
    result = {**base, "status": status, "reasons": reasons}
    store.record_hypothesis_result(hid, now, mode, status, result)
    return result


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Pre-registered strategy experiments against a frozen baseline")
    ap.add_argument("--db", default="optplat.db")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register", help="write a hypothesis down before testing it")
    r.add_argument("--statement", required=True)
    r.add_argument("--challenger", required=True, help='JSON: {"name":"liquid-trend","version":"0.2.0-x","params":{"min_dte":45}}')
    r.add_argument("--criteria", required=True, help='JSON: {"metric":"expectancy_per_trade","min_improvement":5}')
    e = sub.add_parser("evaluate", help="evaluate a hypothesis (confirmatory unless --exploratory)")
    e.add_argument("id")
    e.add_argument("--exploratory", action="store_true")
    e.add_argument("--allow-unverified", action="store_true", help="accept quotes with no exchange timestamp. Research only")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    store = Store(args.db)
    try:
        if args.cmd == "register":
            hid = register(store, args.statement, json.loads(args.challenger), json.loads(args.criteria))
            print(f"Registered {hid}. Confirmatory results will use only data recorded after this moment.")
        elif args.cmd == "list":
            for h in store.list_hypotheses():
                last = store.hypothesis_results(h["id"])
                print(f"{h['id']}  {h['registered_at'][:19]}  {last[-1]['status'] if last else 'NOT_EVALUATED'}  {h['payload']['statement']}")
        else:
            policy = RiskPolicy(require_verified_quote_time=not args.allow_unverified)
            out = evaluate_hypothesis(store, args.id, "exploratory" if args.exploratory else "confirmatory", policy)
            print(json.dumps({k: out[k] for k in ("hypothesis", "mode", "status", "reasons", "snapshots_used", "caveats")}, indent=2))
    except (ValueError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
