"""Plain-English help for the errors a cycle or a lane reports (owner request, 2026-11-27).

Each error string is matched against known patterns and gets: what probably caused it, what fixes it, who acts
(nobody yet, the owner, an agent, the Alerter's shared data service, or an owner decision), and how many cycles in a
row it has appeared. A one-off data hiccup reads as "wait"; the same error three cycles running is flagged.

Display and triage only: nothing here retries, skips, changes a setting or touches an order.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

REPEAT_ALERT = 3  # this many cycles in a row turns a "wait" into something to look at

# who acts
WAIT = "wait"          # usually clears by itself; look only if it repeats
OWNER = "you"          # needs the owner (a setting on the Mac, a decision)
AGENT = "agent"        # a code problem: the scheduled error check opens a fix for review
ALERTER = "alerter"    # the shared IBKR data service (options-alerter), which this repo does not change
DESIGN = "decision"    # working as built; changing it needs an owner decision

_SYM = r"(?P<sym>[A-Z][A-Z0-9.^-]{0,9})"
_CODE_AT = re.compile(r"\[(?P<file>[\w.]+\.py):(?P<line>\d+) in (?P<fn>\w+)\]")

# (kind, pattern, owner, cause, fix). First match wins. {sym} and {detail} are filled from the match.
_RULES: tuple[tuple[str, re.Pattern[str], str, str, str], ...] = (
    ("IBKR_TIER_HELD", re.compile(r"platform IBKR budget held for"), DESIGN,
     "The platform held back a research or lane request so the main account keeps first claim on the IBKR budget.",
     "Working as built: that request used the research fallback; it uses IBKR again once the 10-minute window frees."),
    ("BAR_SHARE_HELD", re.compile(r"platform share of IBKR 5-minute bars used"), DESIGN,
     "The platform held back a 5-minute-bar request to stay inside its share of the shared IBKR budget.",
     "Working as built: the core names keep IBKR bars; other names use the research fallback until the share frees."),
    ("IBKR_BUDGET", re.compile(r"pacing budget exhausted"), WAIT,
     "The shared IBKR service's bar budget (30 requests per 10 minutes, Alerter and platform together) ran out, so "
     "data came from Yahoo or not at all.",
     "Nothing if it clears. If it repeats, see platform_usage in /api/health for which part of the platform asks most."),
    ("FUTURE_TIMESTAMP", re.compile(r"rejected \(FUTURE_TIMESTAMP"), OWNER,
     "This computer's clock is behind the market data, so {sym}'s quotes look like they come from the future.",
     "Turn on System Settings > General > Date & Time > Set time and date automatically (or run: sudo sntp -sS time.apple.com)."),
    ("STALE_SNAPSHOT", re.compile(r"rejected \(STALE_SNAPSHOT"), WAIT,
     "{sym}'s quotes were too old to trust{source_note}.",
     "Nothing if it clears next cycle. If it repeats, the data feed has stopped updating: check the data pill on System."),
    ("EMPTY_CHAIN", re.compile(r"rejected \(EMPTY_CHAIN"), WAIT,
     "No source gave a usable option quote for {sym} this cycle{source_note}.",
     "Nothing if it clears next cycle; {sym} is simply skipped. If it repeats, IBKR's data service is failing for {sym}: "
     "check that TWS is running and the Alerter's data service is up."),
    ("BAD_DATA", re.compile(r"rejected \((BAD_UNDERLYING|BAD_HISTORY)"), WAIT,
     "{sym}'s price or price history came back broken{source_note}.",
     "Nothing if it clears next cycle; {sym} is skipped meanwhile."),
    ("FETCH_FAILED", re.compile(r"^data " + _SYM + r": (?!rejected)"), WAIT,
     "Neither IBKR nor the Yahoo fallback returned data for {sym}{source_note}.",
     "Nothing if it clears next cycle. If it repeats, check TWS and the Alerter's data service."),
    ("LANE_MARKS_PAUSED", re.compile(r"BBO exchange time unverified"), DESIGN,
     "On IBKR data the option lanes refuse quotes whose exchange time is not verified, so they cannot open, price or "
     "exit simulated trades.",
     "Working as built. The proposed fix verifies the one chosen contract with IBKR's timestamp check (the one the main "
     "account's orders use); it needs your OK because it spends the Alerter's shared data budget."),
    ("NO_EXIT_QUOTE", re.compile(r"wanted to close on .* no usable quote|no quote to close at"), WAIT,
     "A held simulated trade should close but there is no quote to close it at; it stays open.",
     "Nothing if a quote returns next pass. If it repeats near expiry, the trade's result will be wrong: look at it."),
    ("DAILY_BARS", re.compile(r"daily bars unavailable"), WAIT,
     "Daily price bars could not be fetched.",
     "Nothing if it clears next pass; signals that need daily bars wait meanwhile."),
    ("TIME_BUDGET", re.compile(r"time budget reached"), WAIT,
     "The scan ran out of time before reading every chain.",
     "Nothing: the rest is read next scan. If it happens every scan, the data service is slow."),
    ("BROKER_POSITIONS", re.compile(r"^positions: "), AGENT,
     "Reading positions from the broker failed.",
     "If it repeats, the broker adapter has a problem: the error check will investigate."),
    ("QUOTES_UNAVAILABLE", re.compile(r"quotes unavailable|held quotes: "), WAIT,
     "Quotes for held contracts could not be fetched, so no premium exit was checked this pass.",
     "Nothing if it clears next pass. If it repeats, check TWS and the Alerter's data service."),
    ("SERVICE_CAPACITY", re.compile(r"Request capacity reached|HTTP 503"), ALERTER,
     "The shared IBKR data service turned the request away (busy or unavailable).",
     "Nothing if it clears. If it repeats, the Alerter and the platform are asking for more than the service allows."),
    ("BOOKKEEPING", re.compile(r"^(record|recorder|recorder purge|recorder quotes|gex|flow|data issue log)\b"), AGENT,
     "Saving or summarising data failed; trading decisions are not affected.",
     "If it repeats, it is a code problem: the error check will investigate."),
)


def _symbol(text: str) -> Optional[str]:
    m = re.match(r"^(?:data |record |recorder |gex |flow )?" + _SYM + r":", text)
    return m.group("sym") if m else None


def explain(error: str, sources: Optional[Mapping[str, str]] = None) -> dict[str, Any]:
    """One error string -> {error, kind, symbol, who, cause, fix, code}. Unknown errors are an agent's to look at."""
    text = str(error)
    sym = _symbol(text)
    src = (sources or {}).get(sym or "", "")
    source_note = f" ({src})" if src else ""
    code_at = _CODE_AT.search(text)
    code = {"file": code_at.group("file"), "line": int(code_at.group("line")), "function": code_at.group("fn")} if code_at else None
    for kind, pattern, who, cause, fix in _RULES:
        if pattern.search(text):
            fill = {"sym": sym or "this symbol", "source_note": source_note}
            return {"error": text, "kind": kind, "symbol": sym, "who": who,
                    "cause": cause.format(**fill), "fix": fix.format(**fill), "code": code}
    if code:
        return {"error": text, "kind": "CODE_ERROR", "symbol": sym, "who": AGENT,
                "cause": f"The platform's own code raised an error in {code['function']} ({code['file']}:{code['line']}).",
                "fix": "A code fix: the scheduled error check opens one for review if it repeats.", "code": code}
    return {"error": text, "kind": "UNKNOWN", "symbol": sym, "who": AGENT,
            "cause": "Not a known error yet.",
            "fix": "The scheduled error check will look at it if it repeats, and teach this list the answer.", "code": None}


def _signature(item: Mapping[str, Any]) -> str:
    return f"{item.get('kind')}:{item.get('symbol') or ''}" if item.get("kind") != "UNKNOWN" else f"UNKNOWN:{item.get('error')}"


def explain_cycle(errors: Iterable[str], previous: Optional[Iterable[Mapping[str, Any]]] = None,
                  sources: Optional[Mapping[str, str]] = None) -> list[dict[str, Any]]:
    """Explain a cycle's errors and count how many cycles in a row each one has appeared.

    ``previous`` is the last cycle's result of this function (kept in the stored cycle report), so the count survives a
    restart. An error absent from the previous cycle starts again at 1."""
    before = {_signature(p): int(p.get("repeats") or 1) for p in (previous or []) if isinstance(p, Mapping)}
    out, seen = [], set()
    for e in errors:
        item = explain(e, sources)
        sig = _signature(item)
        if sig in seen:
            continue
        seen.add(sig)
        item["repeats"] = before.get(sig, 0) + 1
        item["alert"] = item["who"] in (OWNER, AGENT) or item["repeats"] >= REPEAT_ALERT
        out.append(item)
    return out


def error_report(last_cycle: Optional[Mapping[str, Any]], lane_results: Iterable[tuple[str, str, Optional[Mapping[str, Any]]]],
                 mirror: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Everything that went wrong recently, explained, for the dashboard and the scheduled error check.

    ``lane_results`` is (lane, label, stored last result). Lanes run on their own cadence, so their errors carry no
    cycles-in-a-row count. ``mirror`` is the IBKR paper mirror's last state from /api/health, if any."""
    c = last_cycle or {}
    cycle_items = c.get("error_help")
    if not isinstance(cycle_items, list):  # a report stored before this existed
        cycle_items = explain_cycle(c.get("errors") or [])
    lanes = []
    for lane, label, res in lane_results:
        errs = list((res or {}).get("errors") or [])
        if errs:
            items = [{**explain(e), "repeats": None} for e in dict.fromkeys(errs)]
            for it in items:
                it["alert"] = it["who"] in (OWNER, AGENT)
            lanes.append({"lane": lane, "label": label, "at": (res or {}).get("at"), "items": items})
    other = []
    if mirror and mirror.get("state") == "error":
        other.append({"error": f"IBKR paper mirror: {mirror.get('kind') or 'error'}", "kind": "MIRROR_ERROR", "symbol": None,
                      "who": AGENT, "cause": "The last order copied to the IBKR paper account failed (often a timeout talking to TWS).",
                      "fix": "Check that TWS is running on paper port 7497. The simulated order is unaffected; "
                             "if it keeps failing the error check will investigate.",
                      "code": None, "repeats": None, "alert": True, "at": mirror.get("at")})
    items = list(cycle_items) + [i for lane in lanes for i in lane["items"]] + other
    return {"cycle": {"started_at": c.get("started_at"), "items": cycle_items}, "lanes": lanes, "other": other,
            "alerts": sum(1 for i in items if i.get("alert")),
            "note": "Explanations only: nothing here retries, skips or changes a setting."}
