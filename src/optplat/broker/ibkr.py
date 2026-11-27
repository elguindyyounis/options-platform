"""Interactive Brokers PAPER adapter (owner decision 2026-11-26, CLAUDE.md hard rule 1).

Sends DAY limit orders to an IBKR **paper** account through TWS or IB Gateway with ``ib_async``
(``pip install -e .[ibkr]``). It refuses, before any order:

* a host that is not localhost, or a port that is not a paper port (7497 TWS, 4002 Gateway);
* a configured account that does not begin with ``DU``;
* a session in which ANY managed account does not begin with ``DU`` (a live login would show a ``U`` account);
* an order over ``MAX_CONTRACTS_PER_ORDER`` contracts or ``MAX_ORDER_PREMIUM_USD`` of premium, or with a bad price;
* a sell for more than the paper account holds after its other working sells.

Idempotency: ``optplat:<key>`` is IBKR's ``orderRef``, and the broker order id is ``ibkr:<key>``, so a restart finds the same
order by searching working and completed orders. If that search cannot run (disconnected), it raises: "no such order"
is only ever said when IBKR answered. IBKR does not timestamp option bid/ask, so ``get_quote`` never marks a quote
verified; the default risk policy will not trade on its own quotes.

Paper fills are IBKR's simulator, not a real market; keep the ``SimBroker`` numbers as the audit comparison.
"""
from __future__ import annotations

import asyncio
import inspect
import math
import os
import re
import threading
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

from ..models import (
    STATUS_CANCELLED,
    STATUS_FILLED,
    STATUS_PARTIALLY_FILLED,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
    Account,
    BrokerOrderStatus,
    Mode,
    OptionContract,
    OrderIntent,
    Position,
    Quote,
    Right,
    Side,
)
from .base import BrokerAdapter, BrokerRejected, QuoteUnavailable

ALLOWED_PAPER_PORTS = {7497, 4002}
MAX_CONTRACTS_PER_ORDER = 10
MAX_ORDER_PREMIUM_USD = 5_000.0
DEFAULT_CLIENT_ID = 71
# Client ids the Options Alerter (a separate app sharing this TWS and paper account) uses: 91 health, 94 data,
# 95 paper orders, 96 and 98 tools. Two clients with one id knock each other off TWS, so these are refused.
ALERTER_CLIENT_IDS = {91, 94, 95, 96, 98}
REF_PREFIX = "optplat:"   # every order this platform sends carries it; nothing without it is ours
CALL_TIMEOUT_S = 20.0
CONNECT_TIMEOUT_S = 15.0        # per ib_async startup request; it runs several, then executions
CONNECT_CALL_TIMEOUT_S = 75.0   # must exceed ib_async's whole startup sync, or we give up as it succeeds
SETTLE_S = 3.0
_TERMINAL = {"Filled", "Cancelled", "ApiCancelled", "Inactive"}
ID_PREFIX = "ibkr:"


def ibkr_paper_config() -> tuple[str, int, Optional[str]]:
    """Validate connection settings. Refuses anything that is not a local paper session.

    The account may be left unset (owner decision 2026-11-27): it is then taken from TWS, and only when the session
    manages exactly one account and that account is a paper (DU) account. A value that is set must be valid.
    """
    host = os.environ.get("IBKR_HOST", "127.0.0.1")
    port = int(os.environ.get("IBKR_PAPER_PORT", "7497"))
    account = os.environ.get("IBKR_PAPER_ACCOUNT", "")
    if host not in ("localhost", "127.0.0.1"):
        raise ValueError("IBKR host must be local")
    if port not in ALLOWED_PAPER_PORTS:
        raise ValueError("IBKR paper-only port required (7497/4002)")
    if account and not is_paper_account(account):
        raise ValueError("IBKR_PAPER_ACCOUNT must be a paper account id beginning with DU (or leave it unset)")
    return host, port, account or None


def is_paper_account(account: Any) -> bool:
    """IBKR paper accounts begin with DU. Real paper ids can have letters after the prefix (seen on the owner's
    account), so DU + 5-12 capital letters or digits; live accounts begin with U and never match."""
    return isinstance(account, str) and re.fullmatch(r"DU[A-Z0-9]{5,12}", account) is not None


class LoopThread:
    """Runs ib_async on its own event loop thread; callers block with a timeout."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, name="ibkr-paper", daemon=True).start()

    def __call__(self, fn: Callable[..., Any], *args: Any, _timeout: float = CALL_TIMEOUT_S, **kwargs: Any) -> Any:
        async def go() -> Any:
            out = fn(*args, **kwargs)
            return await out if inspect.isawaitable(out) else out
        return asyncio.run_coroutine_threadsafe(go(), self.loop).result(_timeout)


def _safe(text: str) -> str:
    """An error message without account ids, for health output and logs."""
    import re
    return re.sub(r"\b[DU][A-Z]?\d{5,}\b", "<account>", text)[:200]


def _filled(trade: Any) -> int:
    """Contracts filled. ib_async leaves orderStatus.filled at 0 for orders reported as completed (for example after a
    restart); the real count is then the order's filledQuantity (unset is a huge sentinel)."""
    live = float(getattr(trade.orderStatus, "filled", 0) or 0)
    done = getattr(trade.order, "filledQuantity", None)
    done = float(done) if isinstance(done, (int, float)) and 0 <= done < 1e9 else 0.0
    return int(max(live, done))


def _round_limit(price: float, side: Side) -> float:
    """Cents, never past the approved limit: buys round down, sells round up."""
    cents = price * 100
    return (math.floor(cents + 1e-9) if side is Side.BUY_TO_OPEN else math.ceil(cents - 1e-9)) / 100


class IBKRPaperBroker(BrokerAdapter):
    mode = Mode.PAPER
    name = "ibkr_paper"

    def __init__(self, *, ib: Any = None, api: Any = None, runner: Optional[Callable[..., Any]] = None,
                 client_id: Optional[int] = None, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.host, self.port, self._pinned = ibkr_paper_config()
        self.account_id: Optional[str] = self._pinned
        self.client_id = int(os.environ.get("IBKR_ORDER_CLIENT_ID", DEFAULT_CLIENT_ID)) if client_id is None else client_id
        if self.client_id in ALERTER_CLIENT_IDS:
            raise ValueError(f"IBKR client id {self.client_id} belongs to the Options Alerter; use another")
        self._ib, self._api, self._run, self._clock = ib, api, runner, clock
        self._contracts: dict[OptionContract, Any] = {}
        self._lock = threading.RLock()
        self._verified = False
        self.stage = "not connected"

    # ---- connection ------------------------------------------------------------------------------------------------
    def _session(self) -> Any:
        """A connected IB whose every managed account is paper. Raises otherwise; never half-trusts a session."""
        with self._lock:
            if self._ib is None:
                import ib_async  # optional dependency, only needed when the owner enables IBKR
                self._api = ib_async
                self._run = self._run or LoopThread()
                self._ib = self._run(ib_async.IB)
            ib, run = self._ib, self._run
            if not run(ib.isConnected):
                self._verified = False
                self.stage = "connect"
                run(ib.connectAsync, self.host, self.port, clientId=self.client_id, readonly=False,
                    timeout=CONNECT_TIMEOUT_S, account=self.account_id or "", _timeout=CONNECT_CALL_TIMEOUT_S)
            if not self._verified:
                self.stage = "paper-only check"
                accounts = list(run(ib.managedAccounts) or [])
                if not accounts or not all(is_paper_account(a) for a in accounts):
                    run(ib.disconnect)
                    raise RuntimeError("IBKR session is not a paper-only session; refusing to use it")
                if self._pinned is None:
                    if len(accounts) != 1:
                        run(ib.disconnect)
                        raise RuntimeError("IBKR session manages several paper accounts; set IBKR_PAPER_ACCOUNT")
                    self.account_id = accounts[0]
                elif self._pinned not in accounts:
                    run(ib.disconnect)
                    raise RuntimeError("IBKR session does not manage the configured paper account")
                self.stage = "open orders"
                run(ib.reqAllOpenOrdersAsync)   # bind working orders from earlier sessions so idempotency holds
                self._verified = True
            self.stage = "ready"
            return ib

    def healthcheck(self) -> dict[str, Any]:
        try:
            self._session()
        except Exception as exc:  # noqa: BLE001 - report, never raise from a health check
            return {"connected": False, "paper_only": None, "port": self.port, "client_id": self.client_id,
                    "failed_at": self.stage, "reason": type(exc).__name__, "detail": _safe(str(exc))}
        return {"connected": True, "paper_only": True, "port": self.port, "client_id": self.client_id}

    # ---- account ---------------------------------------------------------------------------------------------------
    def get_account(self) -> Account:
        ib = self._session()
        values = {(v.tag, v.currency): v.value for v in self._run(ib.accountValues, self.account_id)}

        def usd(tag: str) -> float:
            raw = values.get((tag, "USD"), values.get((tag, "BASE")))
            num = float(raw) if raw not in (None, "") else math.nan
            if not math.isfinite(num):
                raise RuntimeError(f"IBKR account value {tag} unavailable")
            return num
        premium = sum(p.quantity * p.avg_cost * p.contract.multiplier for p in self.get_positions())
        return Account(equity=usd("NetLiquidation"), cash=max(0.0, usd("TotalCashValue")), open_premium=premium)

    def get_positions(self) -> list[Position]:
        ib = self._session()
        out = []
        for p in self._run(ib.positions, self.account_id):
            c = p.contract
            if getattr(c, "secType", "") != "OPT" or p.position <= 0:
                continue
            mult = int(c.multiplier or 100)
            contract = OptionContract(c.symbol, date.fromisoformat(f"{c.lastTradeDateOrContractMonth[:4]}-"
                                      f"{c.lastTradeDateOrContractMonth[4:6]}-{c.lastTradeDateOrContractMonth[6:8]}"),
                                      Right(c.right[:1]), float(c.strike), mult)
            out.append(Position(contract, int(p.position), float(p.avgCost) / mult))
        return out

    def _qualified(self, contract: OptionContract) -> Any:
        if contract in self._contracts:
            return self._contracts[contract]
        ib = self._session()
        want = self._api.Option(contract.underlying, f"{contract.expiry:%Y%m%d}", contract.strike, contract.right.value,
                                "SMART", multiplier=str(contract.multiplier), currency="USD",
                                tradingClass=contract.underlying)
        rows = [r for r in (self._run(ib.qualifyContractsAsync, want) or []) if r]
        if len(rows) != 1 or rows[0].secType != "OPT" or str(rows[0].multiplier) != str(contract.multiplier):
            raise BrokerRejected("IBKR has no single standard listing for this contract")
        self._contracts[contract] = rows[0]
        return rows[0]

    def get_quote(self, contract: OptionContract) -> Quote:
        ib = self._session()
        try:
            ibc = self._qualified(contract)
        except BrokerRejected as exc:
            raise QuoteUnavailable(str(exc)) from None
        tickers = self._run(ib.reqTickersAsync, ibc) or []
        t = tickers[0] if tickers else None
        bid, ask = (float(getattr(t, "bid", math.nan)), float(getattr(t, "ask", math.nan))) if t else (math.nan, math.nan)
        if t is None or getattr(t, "marketDataType", None) != 1 or not (math.isfinite(bid) and math.isfinite(ask)) \
                or ask <= 0 or bid < 0 or bid > ask:
            raise QuoteUnavailable("No live two-sided IBKR quote")
        return Quote(contract, bid, ask, self._clock(), "ibkr-paper", timestamp_verified=False)

    # ---- orders ----------------------------------------------------------------------------------------------------
    def _mine(self, trade: Any) -> bool:
        # Completed orders from an earlier session can come back with a blank account. The session is verified
        # paper-only and orderRef is our own unique key, so blank counts as ours: missing it could resend an order.
        # The paper account is shared with the Options Alerter: only orders tagged with our prefix are ours.
        return (getattr(trade.order, "account", "") in (self.account_id, "")
                and str(getattr(trade.order, "orderRef", "")).startswith(REF_PREFIX))

    def _status(self, trade: Any) -> BrokerOrderStatus:
        st = trade.orderStatus
        raw, filled = st.status, _filled(trade)
        total = int(trade.order.totalQuantity)
        if raw == "Filled" or (filled and filled >= total):
            mapped = STATUS_FILLED
        elif raw in ("Cancelled", "ApiCancelled"):
            mapped = STATUS_CANCELLED
        elif raw == "Inactive":
            mapped = STATUS_REJECTED if not filled else STATUS_CANCELLED
        else:
            mapped = STATUS_PARTIALLY_FILLED if filled else STATUS_SUBMITTED
        avg = float(st.avgFillPrice) if filled and st.avgFillPrice else None  # None for an earlier session's order
        key = trade.order.orderRef[len(REF_PREFIX):]
        return BrokerOrderStatus(ID_PREFIX + key, key, mapped, filled, avg)

    def _find_trade(self, key: str) -> Optional[Any]:
        ib = self._session()
        for t in self._run(ib.trades):
            if self._mine(t) and t.order.orderRef == REF_PREFIX + key:
                return t
        for t in self._run(ib.reqCompletedOrdersAsync, True) or []:
            if self._mine(t) and t.order.orderRef == REF_PREFIX + key:
                return t
        return None

    def owned_positions(self) -> list[Position]:
        """Long option positions in the paper account that THIS platform's own orders bought (never the Alerter's)."""
        out = []
        with self._lock:
            for pos in self.get_positions():
                ours = self._our_net(self._qualified(pos.contract).conId)
                qty = min(pos.quantity, ours)
                if qty > 0:
                    out.append(Position(pos.contract, qty, pos.avg_cost))
        return out

    def _our_net(self, con_id: Any) -> int:
        """Contracts this platform bought minus those it sold or is selling, for one listing (its own orders only)."""
        ib = self._session()
        seen, net = set(), 0
        for t in list(self._run(ib.trades)) + list(self._run(ib.reqCompletedOrdersAsync, True) or []):
            if not self._mine(t) or getattr(t.contract, "conId", None) != con_id or t.order.orderRef in seen:
                continue
            seen.add(t.order.orderRef)
            filled = _filled(t)
            if t.order.action == "BUY":
                net += filled
            elif t.orderStatus.status in _TERMINAL:
                net -= filled
            else:
                net -= int(t.order.totalQuantity)   # a working sell holds its whole quantity
        return net

    def _settle(self, trade: Any) -> None:
        async def wait() -> None:
            for _ in range(int(SETTLE_S / 0.1)):
                if trade.orderStatus.status not in ("PendingSubmit", "ApiPending", ""):
                    return
                await asyncio.sleep(0.1)
        self._run(wait)

    def submit_limit_order(self, intent: OrderIntent) -> BrokerOrderStatus:
        qty, limit, mult = int(intent.quantity), float(intent.limit_price), intent.contract.multiplier
        if not 1 <= qty <= MAX_CONTRACTS_PER_ORDER:
            raise BrokerRejected(f"IBKR paper orders are limited to 1-{MAX_CONTRACTS_PER_ORDER} contracts")
        if not (math.isfinite(limit) and limit > 0) or qty * limit * mult > MAX_ORDER_PREMIUM_USD:
            raise BrokerRejected(f"IBKR paper order premium must be positive and at most ${MAX_ORDER_PREMIUM_USD:,.0f}")
        if not intent.idempotency_key:
            raise BrokerRejected("An idempotency key is required")
        with self._lock:
            existing = self.find_order_by_client_id(intent.idempotency_key)
            if existing is not None:
                return existing
            ib = self._session()
            ibc = self._qualified(intent.contract)
            if intent.side is Side.SELL_TO_CLOSE:
                # Only what THIS platform bought and has not sold: the account may also hold the Alerter's positions.
                held = sum(p.quantity for p in self.get_positions() if p.contract == intent.contract)
                ours = self._our_net(ibc.conId)
                if qty > min(held, ours):
                    raise BrokerRejected(f"Cannot sell more than this platform holds in the IBKR paper account "
                                         f"(account holds {held}, this platform's orders net {ours})")
            order = self._api.LimitOrder("BUY" if intent.side is Side.BUY_TO_OPEN else "SELL", qty,
                                         _round_limit(limit, intent.side), tif="DAY", account=self.account_id,
                                         orderRef=REF_PREFIX + intent.idempotency_key, outsideRth=False, transmit=True)
            trade = self._run(ib.placeOrder, ibc, order)   # an exception here means "unknown": the manager reconciles
            self._settle(trade)
            return self._status(trade)

    def cancel_order(self, broker_order_id: str) -> BrokerOrderStatus:
        key = broker_order_id[len(ID_PREFIX):] if broker_order_id.startswith(ID_PREFIX) else broker_order_id
        with self._lock:
            trade = self._find_trade(key)
            if trade is None:
                raise RuntimeError("IBKR has no order with that reference")
            if trade.orderStatus.status not in _TERMINAL:
                self._run(self._session().cancelOrder, trade.order)
                self._settle_cancel(trade)
            return self._status(trade)

    def _settle_cancel(self, trade: Any) -> None:
        async def wait() -> None:
            for _ in range(int(SETTLE_S / 0.1)):
                if trade.orderStatus.status in _TERMINAL:
                    return
                await asyncio.sleep(0.1)
        self._run(wait)

    def get_order_status(self, broker_order_id: str) -> BrokerOrderStatus:
        key = broker_order_id[len(ID_PREFIX):] if broker_order_id.startswith(ID_PREFIX) else broker_order_id
        found = self.find_order_by_client_id(key)
        if found is None:
            raise RuntimeError("IBKR has no order with that reference")
        return found

    def find_order_by_client_id(self, client_id: str) -> Optional[BrokerOrderStatus]:
        trade = self._find_trade(client_id)
        return self._status(trade) if trade is not None else None

    def get_open_orders(self) -> list[BrokerOrderStatus]:
        ib = self._session()
        return [self._status(t) for t in self._run(ib.openTrades) if self._mine(t)
                and t.orderStatus.status not in _TERMINAL]
