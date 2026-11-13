"""Options research lanes: the same ideas as the share lanes, expressed as simulated long calls and puts.

What this is: five experiments in their own ledger (``lane_trades``), apart from the options account. A signal on
the underlying (an EMA9 / VWAP cross, a daily pullback, or unusual flow that stuck into the next day) buys ONE
simulated call or put, filled from the real chain quote at the ask and closed at the bid, with a per-contract fee.
Risk on each trade is the premium paid, so nothing here sells an option or can lose more than it cost.

What it is not: an order path. It places no orders, touches no broker, no risk limit and no options position, and
it does not change the engine's ``RiskPolicy`` (which still keeps real entries at 7+ days to expiry). The
"aggressive" variants are looser on purpose, to collect more and different losses to learn from. The results
prove nothing until a pre-registered test says otherwise, and demo data is labelled fictional everywhere.

Anything unknown (no bars, no chain, a failed fetch, no usable quote, an unknown earnings date where the lane
requires one) means no entry. A trade that cannot be marked stays open and is reported, never guessed closed.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Callable, Optional, Sequence

from . import shortterm as st_mod
from . import swing as sw_mod
from .dataquality import check_snapshot
from .diagnostics import describe_exc
from .events import ETFS, EventCalendar
from .market_clock import NY
from .marketdata import ChainRow, MarketDataProvider, MarketSnapshot
from .models import OptionContract, Right, utcnow
from .postmortem import digest, post_mortem
from .scanner import SECTOR_OF, UNIVERSE, session_day
from .shortterm import lane_report
from .store import Store

MULTIPLIER = 100
FEE_PER_CONTRACT = 0.65          # each way, per contract
RUN_EVERY = {"short": timedelta(seconds=120), "swing": timedelta(minutes=60), "flow": timedelta(minutes=30)}
MAX_ENTRIES_PER_STEP = 3
MAX_CHAIN_READS_PER_STEP = 8
MAX_STRIKE_MISS_PCT = 5.0        # the chosen strike may sit this far (of spot) from the target before the lane gives up
SCAN_MAX_AGE = timedelta(hours=20)


@dataclass(frozen=True)
class Params:
    lane: str
    label: str
    kind: str                    # "short" | "swing" | "flow"
    why: str
    budget_usd: float            # premium spent per trade, at most
    max_open: int
    max_per_sector: int
    dte_min: int
    dte_max: int
    otm_pct: float               # how far out of the money the strike is aimed, in percent of spot
    max_spread_pct: float
    min_oi: int
    min_volume: int
    min_ask: float
    stop_pct: float              # premium loss (from the ask paid) that closes the trade
    target_pct: float
    max_hold_bars: int           # trading days for swing and flow; unused for short-term
    experimental: bool           # looser entry rules, on purpose
    both_ways: bool              # may buy puts as well as calls
    earnings_gate: bool          # single stocks need a known, clear earnings calendar
    symbols: tuple[str, ...]
    max_per_name: int = 1        # open positions allowed in one name (stacking)
    stack: str = "none"          # "none", "winners" (add only to winners) or "any"


EXTRA_SHORT = ("AMD", "META", "AMZN", "MSFT", "GOOGL", "PLTR", "COIN", "SMCI", "MU", "AVGO")

SHORT_BASE = Params("shortterm-options-base", "Short-term options, base", "short",
                    "EMA9 crossing above the session VWAP buys a call, crossing below buys a put. Weekly expiry, at the money.",
                    1000, 4, 3, 2, 10, 0.0, 12.0, 100, 10, 0.20, 30, 50, 0, False, True, False, st_mod.LANE_SYMBOLS)
SHORT_AGGR = Params("shortterm-options-aggr", "Short-term options, aggressive", "short",
                    "The same signal on more names, with expiry as short as today, a strike slightly out of the money, a wider spread allowed, five times the size, up to three positions stacked in one name, and wider stop and target.",
                    5000, 15, 8, 0, 4, 0.5, 20.0, 25, 5, 0.10, 40, 100, 0, True, True, False, st_mod.LANE_SYMBOLS + EXTRA_SHORT,
                    max_per_name=3, stack="any")
SWING_BASE = Params("swing-options-base", "Swing options, base", "swing",
                    "The swing pullback rule, expressed as a call 30 to 60 days out at the money instead of shares.",
                    2500, 6, 3, 30, 60, 0.0, 12.0, 100, 10, 0.50, 40, 80, 10, False, False, True, sw_mod.SYMBOLS)
SWING_AGGR = Params("swing-options-aggr", "Swing options, aggressive", "swing",
                    "A looser pullback rule (no 20/50-day filter, RSI at or below 50, moves up to 8% allowed), plus puts on a bounce in a downtrend, "
                    "shorter expiry, a strike out of the money, earnings allowed and recorded, and up to three positions stacked in one name.",
                    10000, 20, 8, 14, 35, 3.0, 20.0, 25, 5, 0.30, 50, 120, 8, True, True, False, sw_mod.SYMBOLS,
                    max_per_name=3, stack="any")
FLOW = Params("flow-options", "Unusual flow that stuck", "flow",
              "When a contract had a very high volume to open interest ratio and its open interest rose the next day, buy a call (if the read is bullish) or a put (if bearish) on the same name. Double size when the contract had almost no open interest before the flow; add a second position only when the first is winning.",
              5000, 15, 6, 21, 60, 1.0, 15.0, 50, 5, 0.30, 50, 100, 10, True, True, False, (),
              max_per_name=2, stack="winners")
# Frozen reference lane (challenge 3). Written out in full on purpose, NOT derived from SHORT_BASE, so that tuning
# SHORT_BASE can never silently move the yardstick. Its settings are pinned by FROZEN_FINGERPRINT and a test; changing
# either is an owner decision, and a changed lane must get a new lane id so old and new results are never mixed.
FROZEN_BASELINE = Params("frozen-baseline-options", "Frozen baseline (never tuned)", "short",
                         "A fixed copy of the first short-term rule (EMA9/VWAP, weekly expiry, at the money, $1,000 a trade). Its settings are pinned by a fingerprint and never change, so every other lane can be compared with the same yardstick.",
                         1000, 4, 3, 2, 10, 0.0, 12.0, 100, 10, 0.20, 30, 50, 0, False, True, False, st_mod.LANE_SYMBOLS)


def params_fingerprint(p: Params) -> str:
    return hashlib.sha256(repr(p).encode()).hexdigest()


FROZEN_FINGERPRINT = "47e1f4eeb081e86c5f9c711eaac3bd599dadf7a7efdb3c7724f541aa4f119f99"

ALL_PARAMS = (SHORT_BASE, SHORT_AGGR, SWING_BASE, SWING_AGGR, FLOW, FROZEN_BASELINE)

EXIT_TEXT = {
    "stop": "The option's bid fell to the stop set when the trade opened.",
    "target": "The option's bid reached the profit target set when the trade opened.",
    "vwap_lost": "The underlying closed back through the session VWAP, against the position.",
    "flat_by_close": "Closed before the end of the session: the short-term lanes never hold overnight.",
    "carried_over": "Found open from an earlier day and closed at the first usable quote.",
    "trend_break": "The underlying closed through its 50-day average, against the position.",
    "time": "The holding limit passed without the stop or the target.",
    "expiry_near": "Closed within two days of expiry to stay clear of assignment and pin risk.",
    "expired_unmarked": "The contract expired with no usable quote, so it was closed at its intrinsic value.",
}


# ------------------------------------------------------------ small pure helpers
def intrinsic(right: str, strike: float, spot: Optional[float]) -> float:
    if spot is None:
        return 0.0
    return max(0.0, spot - strike) if right == "C" else max(0.0, strike - spot)


def pick_contract(snap: MarketSnapshot, right: Right, now: datetime, p: Params) -> Optional[ChainRow]:
    """The row nearest the aimed strike inside the expiry window that passes the lane's quote limits, or None."""
    spot = snap.underlying
    target = spot * (1 + p.otm_pct / 100) if right is Right.CALL else spot * (1 - p.otm_pct / 100)
    mid_dte = (p.dte_min + p.dte_max) / 2
    best: Optional[tuple[tuple[float, float], ChainRow]] = None
    for r in snap.rows:
        c = r.contract
        if c.right is not right:
            continue
        dte = (c.expiry - now.date()).days
        if not p.dte_min <= dte <= p.dte_max:
            continue
        if not (r.bid > 0 and r.ask >= r.bid and r.ask >= p.min_ask):  # a zero bid has no exit
            continue
        if (r.ask - r.bid) / r.ask * 100 > p.max_spread_pct or (r.open_interest or 0) < p.min_oi or (r.volume or 0) < p.min_volume:
            continue
        miss = abs(c.strike - target) / spot * 100
        if miss > MAX_STRIKE_MISS_PCT:
            continue
        key = (round(miss, 3), abs(dte - mid_dte))
        if best is None or key < best[0]:
            best = (key, r)
    return best[1] if best else None


def short_signal(r: dict[str, Any], p: Params) -> Optional[str]:
    if st_mod.entry_signal(r):
        return "C"
    if p.both_ways and r["prev_ema"] >= r["prev_vwap"] and r["ema"] < r["vwap"] and r["close"] < r["vwap"]:
        return "P"
    return None


def swing_signal(r: dict[str, Any], p: Params) -> Optional[str]:
    if not p.experimental:
        return "C" if sw_mod.entry_signal(r) else None
    if abs(r["day_move_pct"]) > 8.0:
        return None
    if r["close"] > r["sma_slow"] and r["rsi_dip"] <= 50 and r["rsi"] > r["rsi_prev"] and r["close"] > r["prev_close"]:
        return "C"
    if p.both_ways and r["close"] < r["sma_slow"] and r["rsi_peak"] >= 55 and r["rsi"] < r["rsi_prev"] and r["close"] < r["prev_close"]:
        return "P"
    return None


def rules_text(p: Params) -> list[str]:
    ways = "calls and puts" if p.both_ways else "calls only"
    stack = {"none": "Never adds to a name it already holds.", "winners": f"May hold up to {p.max_per_name} positions in a name, adding only while the earlier ones are winning.",
             "any": f"May hold up to {p.max_per_name} positions in one name and adds whatever the earlier ones are doing, to learn whether stacking pays."}[p.stack]
    rows = [p.why,
            f"Buys {ways}, one contract per name, {p.dte_min} to {p.dte_max} days to expiry, aimed {p.otm_pct:g}% out of the money, spread at most {p.max_spread_pct:g}%, "
            f"open interest at least {p.min_oi}, at most ${p.budget_usd:,.0f} of premium risked per trade.",
            f"Filled at the ask, closed at the bid, ${FEE_PER_CONTRACT} per contract each way. Stop at {p.stop_pct:g}% of the premium, target at {p.target_pct:g}%."]
    rows.append(stack)
    if p.kind == "short":
        rows.append(f"Entries {st_mod.ENTRY_FROM:%H:%M} to {st_mod.ENTRY_UNTIL:%H:%M} New York time, flat by {st_mod.FLAT_BY:%H:%M}, also closed when the underlying closes back through VWAP.")
    else:
        rows.append(f"Held at most {p.max_hold_bars} trading days; closed within 2 days of expiry; at most {p.max_open} open and {p.max_per_sector} per sector.")
    return rows


LIMITATIONS = (
    "Free option quotes are delayed and unofficial. Fills at the ask and bid are an assumption: a real order could fill worse, or not at all in a thin contract.",
    "A premium stop or target is checked each time the lane runs, not continuously, so a real stop could have triggered sooner or later.",
    "These are simulated trades in a separate ledger. No order is sent anywhere and the risk policy is untouched.",
    "The aggressive variants are loose on purpose. Their losses are the point; their wins prove nothing.",
    "Large simulated sizes assume fills a real market may not give: each trade records its size against the contract's volume and open interest, and an oversized one is tagged.",
    "Buy or sell, and opened or closed, for the flow lane are inferred from one last price and a next-day open interest change.",
)


# ------------------------------------------------------------ a short-lived cache so lanes share requests
class Feed:
    """Several lanes reading the same name in the same minute make one request."""

    def __init__(self, provider: MarketDataProvider, clock: Callable[[], datetime], ttl_s: float = 60.0, daily_ttl_s: float = 900.0) -> None:
        self.provider, self.clock, self.ttl_s, self.daily_ttl_s = provider, clock, ttl_s, daily_ttl_s
        self._cache: dict[Any, tuple[datetime, Any]] = {}
        self._lock = threading.Lock()

    def _cached(self, key: Any, ttl: float, load: Callable[[], Any]) -> Any:
        now = self.clock()
        with self._lock:
            hit = self._cache.get(key)
        if hit and 0 <= (now - hit[0]).total_seconds() < ttl:
            return hit[1]
        value = load()
        with self._lock:
            self._cache[key] = (now, value)
        return value

    def intraday(self, sym: str):
        return self._cached(("i", sym), self.ttl_s, lambda: self.provider.intraday_bars(sym))

    def window(self, sym: str, lo: int, hi: int, n: int) -> MarketSnapshot:
        return self._cached(("w", sym, lo, hi, n), self.ttl_s, lambda: self.provider.snapshot_window(sym, lo, hi, n))

    def daily(self, symbols: Sequence[str], months: int):
        return self._cached(("d", tuple(symbols), months), self.daily_ttl_s, lambda: self.provider.daily_bars(symbols, months=months))  # type: ignore[call-arg]


# ------------------------------------------------------------ the lane
class OptionLane:
    def __init__(self, provider: MarketDataProvider, store: Store, params: Params, feed: Feed, *, clock: Callable[[], datetime] = utcnow,
                 calendar: Optional[EventCalendar] = None) -> None:
        self.provider, self.store, self.p, self.feed, self.clock, self.calendar = provider, store, params, feed, clock, calendar
        self._lock = threading.Lock()

    # -- bookkeeping. ``held`` is a list of open trades: a lane may hold several in one name when it is allowed to stack.
    def _held(self) -> list[dict[str, Any]]:
        return [t for t in self.store.lane_trades(self.p.lane, self.provider.fictional, 2000) if t["closed_at"] is None]

    def _new_out(self, now: datetime) -> dict[str, Any]:
        return {"lane": self.p.lane, "at": now.isoformat(), "opened": [], "closed": [], "errors": [], "skips": [], "skipped": 0}

    def _throttled(self, now: datetime, force: bool, out: dict[str, Any]) -> bool:
        key = f"optlane_last_run:{self.p.lane}"
        last = self.store.get_state(key, "")
        if not force and last and now - datetime.fromisoformat(last) < RUN_EVERY[self.p.kind]:
            out["note"] = "throttled"
            return True
        self.store.set_state(key, now.isoformat())
        return False

    def _may_open(self, sym: str, held: list[dict[str, Any]], marks: dict[str, tuple[float, float]]) -> bool:
        """Book size, sector share, and whether a position already in this name may be added to.

        Stacking is the experiment: ``none`` never adds to a name, ``winners`` adds only when every position already
        held in it is above its entry (pyramiding), ``any`` adds whatever the open ones are doing. Which of these
        pays is what the trades' post-mortems will show, so a stack is recorded and tagged."""
        p = self.p
        if len(held) >= p.max_open:
            return False
        sec = SECTOR_OF.get(sym, sym)
        if sum(1 for t in held if SECTOR_OF.get(t["symbol"], t["symbol"]) == sec) >= p.max_per_sector:
            return False
        mine = [t for t in held if t["symbol"] == sym]
        if not mine:
            return True
        if len(mine) >= p.max_per_name or p.stack == "none":
            return False
        if p.stack == "winners":
            return all((marks.get(t["open_payload"]["contract"]) or (0.0, 0.0))[0] > t["entry_price"] for t in mine)
        return True

    def _earnings_state(self, sym: str, today: date) -> str:
        if sym.upper() in ETFS:
            return "FUND"
        if self.calendar is None:
            return "UNKNOWN"
        ev = self.calendar.earnings(sym, today, today + timedelta(days=int(self.p.max_hold_bars * 1.5) + sw_mod.EARNINGS_BUFFER_DAYS))
        return "UNKNOWN" if ev is None else ("SOON" if ev else "CLEAR")

    # -- marking
    def _marks(self, held: list[dict[str, Any]], now: datetime, out: dict[str, Any]) -> dict[str, tuple[float, float]]:
        if not held:
            return {}
        contracts = []
        for t in held:
            o = t["open_payload"]
            contracts.append(OptionContract(t["symbol"], date.fromisoformat(o["expiry"]), Right(o["right"]), o["strike"]))
        try:
            quotes = self.provider.quotes_for(contracts)
        except Exception as exc:  # noqa: BLE001 - no marks means no premium exits this pass, and it is shown
            out["errors"].append(f"quotes unavailable: {type(exc).__name__}: {str(exc)[:80]}")
            return {}
        marks = {q.contract.occ_symbol.strip(): (q.bid, q.ask) for q in quotes if q.is_valid()}
        # Remember how old each mark was and whether its time came from the venue, so a close can store it (display only).
        self._mark_meta = {q.contract.occ_symbol.strip(): {"exit_quote_at": q.as_of.isoformat(), "exit_quote_age_s": round(q.age_seconds(now), 1),
                                                           "exit_quote_verified": bool(q.timestamp_verified)} for q in quotes if q.is_valid()}
        for t in held:
            m = marks.get(t["open_payload"]["contract"])
            if m:
                self.store.set_state(f"lane_mark:{t['id']}", json.dumps({"bid": m[0], "ask": m[1], "at": now.isoformat()}))
        return marks

    # -- closing and opening
    def _close(self, t: dict[str, Any], bid: float, reason: str, now: datetime, out: dict[str, Any], info: dict[str, Any]) -> bool:
        fees = round(t["quantity"] * FEE_PER_CONTRACT, 2)
        info = {**info, "fees_close": fees}
        if info.get("bid") is not None:  # a priced exit; an intrinsic-value close (bid None) has no quote to age
            meta = getattr(self, "_mark_meta", {}).get(t["open_payload"].get("contract"))
            info.update(meta or {"exit_quote_at": None, "exit_quote_age_s": None, "exit_quote_verified": False})
        info["postmortem"] = post_mortem(t, bid, reason, now, info)
        if self.store.lane_close(t["id"], now, bid, reason, info):
            out["closed"].append({"symbol": t["symbol"], "reason": reason})
            return True
        return False

    def _enter(self, sym: str, right: str, now: datetime, out: dict[str, Any], signal: dict[str, Any], held: list[dict[str, Any]],
               extra: Optional[dict[str, Any]] = None, budget_mult: float = 1.0) -> Optional[dict[str, Any]]:
        p = self.p
        try:
            chk = check_snapshot(self.feed.window(sym, p.dte_min, p.dte_max, 3), now)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"{sym}: chain unavailable ({describe_exc(exc)})")
            return None
        if chk.snapshot is None:
            out["errors"].append(f"{sym}: chain rejected by the data-quality gate ({chk.issues[-1].kind if chk.issues else 'unknown'})")
            return None
        row = pick_contract(chk.snapshot, Right(right), now, p)
        if row is None:
            out["skips"].append(f"{sym}: no {'call' if right == 'C' else 'put'} met the expiry, spread and open interest limits")
            return None
        budget = p.budget_usd * budget_mult
        qty = int(budget // (row.ask * MULTIPLIER))
        if qty < 1:
            out["skips"].append(f"{sym}: one contract costs more than the ${budget:,.0f} budget")
            return None
        c = row.contract
        mine = [t for t in held if t["symbol"] == sym]
        payload = {"kind": p.kind, "variant": p.label, "contract": c.occ_symbol.strip(), "right": right, "strike": c.strike,
                   "expiry": c.expiry.isoformat(), "dte": (c.expiry - now.date()).days, "bid": row.bid, "ask": row.ask,
                   "spread_pct": round((row.ask - row.bid) / row.ask * 100, 2), "iv": row.iv, "open_interest": row.open_interest,
                   "volume": row.volume, "underlying_price": signal.get("close") or chk.snapshot.underlying, "chain_underlying": chk.snapshot.underlying,
                   "multiplier": MULTIPLIER, "fee_per_contract": FEE_PER_CONTRACT, "fees_open": round(qty * FEE_PER_CONTRACT, 2),
                   "stop_pct": p.stop_pct, "target_pct": p.target_pct, "max_hold_bars": p.max_hold_bars, "sector": SECTOR_OF.get(sym),
                   "signal": signal, "earnings_state": "n/a", "budget_usd": round(budget), "stack_index": len(mine),
                   "stacked_on": [t["id"] for t in mine],
                   "size_vs_volume_pct": round(qty / row.volume * 100, 1) if row.volume else None,
                   "size_vs_oi_pct": round(qty / row.open_interest * 100, 1) if row.open_interest else None, **(extra or {})}
        veto, new_qty = self._review(sym, right, row, qty, payload, held, now)
        if veto:
            out["skips"].append(f"{sym}: {veto}")
            return None
        if new_qty != qty:
            qty = new_qty
            payload.update({"fees_open": round(qty * FEE_PER_CONTRACT, 2), "size_vs_volume_pct": round(qty / row.volume * 100, 1) if row.volume else None,
                            "size_vs_oi_pct": round(qty / row.open_interest * 100, 1) if row.open_interest else None})
        tid = self.store.lane_open(p.lane, sym, now, row.ask, qty, self.provider.fictional, payload)
        out["opened"].append({"symbol": sym, "contract": payload["contract"], "right": right, "stack_index": len(mine)})
        made = {"id": tid, "symbol": sym, "open_payload": payload, "entry_price": row.ask, "quantity": qty, "opened_at": now.isoformat()}
        held.append(made)
        return made

    def _review(self, sym: str, right: str, row: ChainRow, qty: int, payload: dict[str, Any], held: list[dict[str, Any]],
                now: datetime) -> tuple[Optional[str], int]:
        """Last look before a trade opens. Returns (reason to refuse or None, quantity to buy). The base lanes accept
        everything their rules already let through; the challenge account overrides this with a critic."""
        return None, qty

    # -- the premium rules every lane shares
    def _premium_exit(self, t: dict[str, Any], mark: Optional[tuple[float, float]]) -> Optional[str]:
        if mark is None:
            return None
        bid, entry = mark[0], t["entry_price"]
        if bid <= entry * (1 - t["open_payload"]["stop_pct"] / 100):
            return "stop"
        if bid >= entry * (1 + t["open_payload"]["target_pct"] / 100):
            return "target"
        return None

    # -- one pass
    def step(self, force: bool = False) -> dict[str, Any]:
        with self._lock:
            now = self.clock()
            out = self._new_out(now)
            if self._throttled(now, force, out):
                return out
            try:
                {"short": self._step_short, "swing": self._step_swing, "flow": self._step_flow}[self.p.kind](now, out)
            except Exception as exc:  # noqa: BLE001 - a research lane must never raise into the engine
                out["errors"].append(describe_exc(exc))
            self._remember(out)
            return out

    def _remember(self, out: dict[str, Any]) -> None:
        """Keep what the last check did and why it did not trade, so the dashboard can answer "why no trades?"."""
        try:
            self.store.set_state(f"optlane_last_result:{self.p.lane}", json.dumps({
                "at": out["at"], "opened": len(out["opened"]), "closed": len(out["closed"]), "skipped": out.get("skipped", 0),
                "errors": [str(e)[:220] for e in out["errors"][:8]], "error_count": len(out["errors"]),
                "skips": [str(x)[:160] for x in out["skips"][:8]], "skip_count": len(out["skips"])}))
        except Exception:  # noqa: BLE001 - bookkeeping must never stop a lane
            pass

    def _step_short(self, now: datetime, out: dict[str, Any]) -> None:
        p = self.p
        held = self._held()
        marks = self._marks(held, now, out)
        in_window = st_mod.in_entry_window(now)
        for sym in p.symbols:
            mine = [t for t in held if t["symbol"] == sym]
            if not mine and not in_window:
                continue
            try:
                r = st_mod.read(self.feed.intraday(sym), now)
            except Exception as exc:  # noqa: BLE001
                out["errors"].append(f"{sym}: {type(exc).__name__}: {str(exc)[:80]}")
                r = None
            fresh = r is not None and (now - r["bar_end"]).total_seconds() <= st_mod.MAX_BAR_AGE_S
            for t in mine:
                self._short_exit(t, marks.get(t["open_payload"]["contract"]), r if fresh else None, now, out, held)
            if not fresh or r is None:
                continue
            key = f"optlane_bar:{p.lane}:{sym}"
            if self.store.get_state(key, "") == r["bar_ts"].isoformat():
                continue
            self.store.set_state(key, r["bar_ts"].isoformat())
            right = short_signal(r, p)
            if right is None:
                continue
            if not self._may_open(sym, held, marks):
                out["skipped"] += 1
                continue
            self._enter(sym, right, now, out, {"bar": r["bar_ts"].isoformat(), "close": round(r["close"], 4), "ema": round(r["ema"], 4),
                                                "vwap": round(r["vwap"], 4), "direction": "up" if right == "C" else "down"}, held)

    def _short_exit(self, t: dict[str, Any], mark: Optional[tuple[float, float]], r: Optional[dict[str, Any]], now: datetime,
                    out: dict[str, Any], held: list[dict[str, Any]]) -> None:
        o = t["open_payload"]
        reason: Optional[str] = None
        if datetime.fromisoformat(t["opened_at"]).astimezone(NY).date() != now.astimezone(NY).date():
            reason = "carried_over"
        elif now.astimezone(NY).time() >= st_mod.FLAT_BY:
            reason = "flat_by_close"
        else:
            reason = self._premium_exit(t, mark)
            if reason is None and r is not None:
                if (o["right"] == "C" and r["close"] < r["vwap"]) or (o["right"] == "P" and r["close"] > r["vwap"]):
                    reason = "vwap_lost"
        if reason is None:
            return
        if mark is None:
            out["errors"].append(f"{t['symbol']}: wanted to close on {reason} but there is no usable quote; it stays open")
            return
        info = {"underlying": None if r is None else round(r["close"], 4), "bid": mark[0], "ask": mark[1],
                "spread_pct": round((mark[1] - mark[0]) / mark[1] * 100, 2) if mark[1] > 0 else None}
        if self._close(t, mark[0], reason, now, out, info):
            held[:] = [h for h in held if h["id"] != t["id"]]

    def _step_swing(self, now: datetime, out: dict[str, Any]) -> None:
        p = self.p
        held = self._held()
        marks = self._marks(held, now, out)
        try:
            raw = self.feed.daily(p.symbols, sw_mod.BARS_MONTHS)
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"daily bars unavailable: {type(exc).__name__}: {str(exc)[:100]}")
            raw = {}
        reads = {sym: sw_mod.read(raw.get(sym, []), now) for sym in p.symbols}
        for t in list(held):
            self._swing_exit(t, marks.get(t["open_payload"]["contract"]), reads.get(t["symbol"]), now, out, held)
        signals = []
        for sym in p.symbols:
            r = reads.get(sym)
            if r is None:
                continue
            key = f"optlane_bar:{p.lane}:{sym}"
            if self.store.get_state(key, "") == r["day"].isoformat():
                continue
            self.store.set_state(key, r["day"].isoformat())
            right = swing_signal(r, p)
            if right:
                signals.append((r["rsi_dip"] if right == "C" else -r["rsi_peak"], sym, right, r))
        signals.sort(key=lambda x: (x[0], x[1]))   # the deepest dip, or the highest bounce, first
        entries = reads_done = 0
        for _, sym, right, r in signals:
            if entries >= MAX_ENTRIES_PER_STEP or reads_done >= MAX_CHAIN_READS_PER_STEP:
                out["skipped"] += 1
                continue
            if not self._may_open(sym, held, marks):
                out["skipped"] += 1
                continue
            state = self._earnings_state(sym, now.date())
            if p.earnings_gate and state not in ("FUND", "CLEAR"):
                out["skipped"] += 1
                continue
            reads_done += 1
            made = self._enter(sym, right, now, out, {"bar_day": r["day"].isoformat(), "close": round(r["close"], 4), "rsi": r["rsi"],
                                                       "sma_slow": round(r["sma_slow"], 4), "direction": "up" if right == "C" else "down"},
                               held, {"bar_day": r["day"].isoformat(), "earnings_state": state})
            if made:
                entries += 1

    def _long_exit(self, t: dict[str, Any], mark: Optional[tuple[float, float]], r: Optional[dict[str, Any]], now: datetime, out: dict[str, Any],
                   held: list[dict[str, Any]], trend_rule: bool) -> None:
        o, sym = t["open_payload"], t["symbol"]
        reason = self._premium_exit(t, mark)
        if reason is None and (date.fromisoformat(o["expiry"]) - now.date()).days <= 2:
            reason = "expiry_near"
        if reason is None and trend_rule and r is not None and ((o["right"] == "C" and r["close"] < r["sma_slow"]) or (o["right"] == "P" and r["close"] > r["sma_slow"])):
            reason = "trend_break"
        if reason is None:
            opened_day = o.get("bar_day") or datetime.fromisoformat(t["opened_at"]).date().isoformat()
            held_bars = sum(1 for d in r["days"] if d.isoformat() > opened_day) if r is not None else \
                int((now.date() - date.fromisoformat(opened_day)).days / 1.5)
            if held_bars >= o.get("max_hold_bars", self.p.max_hold_bars):
                reason = "time"
        if reason is None:
            return
        spot = None if r is None else round(r["close"], 4)
        if mark is None:
            if (date.fromisoformat(o["expiry"]) - now.date()).days < 0:
                info = {"underlying": spot, "bid": None, "spread_pct": None}
                if self._close(t, round(intrinsic(o["right"], o["strike"], spot), 4), "expired_unmarked", now, out, info):
                    held[:] = [h for h in held if h["id"] != t["id"]]
            else:
                out["errors"].append(f"{sym}: wanted to close on {reason} but there is no usable quote; it stays open")
            return
        info = {"underlying": spot, "bid": mark[0], "ask": mark[1], "spread_pct": round((mark[1] - mark[0]) / mark[1] * 100, 2) if mark[1] > 0 else None}
        if self._close(t, mark[0], reason, now, out, info):
            held[:] = [h for h in held if h["id"] != t["id"]]

    def _swing_exit(self, t, mark, r, now, out, held) -> None:
        self._long_exit(t, mark, r, now, out, held, trend_rule=True)

    def _step_flow(self, now: datetime, out: dict[str, Any]) -> None:
        p = self.p
        held = self._held()
        marks = self._marks(held, now, out)
        reads: dict[str, Any] = {}
        if held:
            names = sorted({t["symbol"] for t in held})
            try:
                raw = self.feed.daily(names, sw_mod.BARS_MONTHS)
                reads = {s: sw_mod.read(raw.get(s, []), now) for s in names}
            except Exception as exc:  # noqa: BLE001
                out["errors"].append(f"daily bars unavailable: {type(exc).__name__}: {str(exc)[:100]}")
        for t in list(held):
            self._long_exit(t, marks.get(t["open_payload"]["contract"]), reads.get(t["symbol"]), now, out, held, trend_rule=False)
        scan = self.store.latest_scan(self.provider.fictional)
        if not scan:
            out["note"] = "no scan yet"
            return
        if scan.get("session_day") != session_day(now).isoformat() or now - datetime.fromisoformat(scan["as_of"]) > SCAN_MAX_AGE:
            out["note"] = "the latest scan is not from this session"
            return
        entries = 0
        for f in scan.get("follow_ups", []):
            sym = f["symbol"]
            seen = f"optlane_seen:{f['contract']}:{f['prior_day']}"
            extreme = f.get("prior_low_oi") or (f.get("prior_ratio") or 99) >= 5
            if f["oi_verdict"] != "OI_ROSE" or f["lean"] not in ("BULLISH", "BEARISH") or not extreme or self.store.get_state(seen, ""):
                continue
            self.store.set_state(seen, now.isoformat())
            if entries >= MAX_ENTRIES_PER_STEP or not self._may_open(sym, held, marks):
                out["skipped"] += 1
                continue
            # conviction sizing: a contract that was very thin before the flow, and whose open interest then grew, gets double size
            conviction = 2.0 if f.get("prior_low_oi") else 1.0
            made = self._enter(sym, "C" if f["lean"] == "BULLISH" else "P", now, out,
                               {"from_contract": f["contract"], "prior_day": f["prior_day"], "prior_volume": f["prior_volume"], "prior_oi": f["prior_oi"],
                                "oi_change": f["oi_change"], "position_read": f["position_read"], "prior_ratio": f.get("prior_ratio"),
                                "oi_sessions": f.get("oi_sessions"), "oi_window_clean": f.get("oi_window_clean"),
                                "direction": "up" if f["lean"] == "BULLISH" else "down", "conviction_mult": conviction}, held,
                               {"earnings_state": self._earnings_state(sym, now.date())}, budget_mult=conviction)
            if made:
                entries += 1


# ------------------------------------------------------------ all five together
class OptionLanes:
    def __init__(self, provider: MarketDataProvider, store: Store, *, clock: Callable[[], datetime] = utcnow,
                 calendar: Optional[EventCalendar] = None) -> None:
        self.provider, self.store, self.clock = provider, store, clock
        self.feed = Feed(provider, clock)
        self.lanes = [OptionLane(provider, store, p, self.feed, clock=clock, calendar=calendar) for p in ALL_PARAMS]
        from .challenge import ChallengeLane  # imported here: the challenge module builds on this one

        self.challenge = ChallengeLane(provider, store, self.feed, clock=clock, calendar=calendar)

    def step(self, force: bool = False) -> list[dict[str, Any]]:
        out = [lane.step(force) for lane in self.lanes]
        try:
            self.challenge.step(force)  # its own account and history; kept out of the five-lane list
        except Exception:  # noqa: BLE001 - a research account must never raise into the engine
            pass
        return out

    def reports(self, now: datetime) -> dict[str, Any]:
        fict = self.provider.fictional
        lanes, closed_all = [], []
        for p in ALL_PARAMS:
            rep = lane_report(self.store, p.lane, fict, now, rules=rules_text(p), limitations=LIMITATIONS, symbols=p.symbols or UNIVERSE, exit_text=EXIT_TEXT)
            raw = self.store.get_state(f"optlane_last_result:{p.lane}", "")
            lanes.append({**rep, "last_check": json.loads(raw) if raw else None, "label": p.label, "kind": p.kind, "why": p.why, "experimental": p.experimental,
                          "params": {"budget_usd": p.budget_usd, "max_open": p.max_open, "dte": [p.dte_min, p.dte_max], "otm_pct": p.otm_pct,
                                     "stop_pct": p.stop_pct, "target_pct": p.target_pct, "both_ways": p.both_ways}})
            closed_all += self.store.lane_trades(p.lane, fict, 500)
        closed = [t for t in closed_all if t["closed_at"] is not None]
        return {"fictional": fict, "as_of": now.isoformat(), "lanes": lanes, "digest": digest(closed)}
