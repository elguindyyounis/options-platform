"""IBKR paper adapter against a fake IB session (synthetic fixtures only; no connection to IBKR).

Runs the shared broker conformance suite, then the paper-only guards. A real paper run is separate and manual.
"""
import asyncio
import inspect
from types import SimpleNamespace

import pytest

from conformance import BrokerConformance
from helpers import CONTRACT, make_intent
from optplat.broker import BrokerRejected
from optplat.broker import ibkr
from optplat.models import Side

ACCOUNT = "DU1234567"


def run_inline(fn, *args, _timeout=None, **kwargs):
    out = fn(*args, **kwargs)
    return asyncio.run(out) if inspect.isawaitable(out) else out


class FakeApi:
    @staticmethod
    def Option(symbol, expiry, strike, right, exchange, multiplier="100", currency="USD", tradingClass=""):
        return SimpleNamespace(secType="OPT", symbol=symbol, lastTradeDateOrContractMonth=expiry, strike=strike,
                               right=right, multiplier=multiplier, conId=0)

    @staticmethod
    def LimitOrder(action, qty, price, **kw):
        return SimpleNamespace(action=action, totalQuantity=qty, lmtPrice=price, orderType="LMT", **kw)


class FakeIB:
    def __init__(self, accounts=(ACCOUNT,)):
        self.accounts = list(accounts)
        self.connected = False
        self.bid, self.ask = 1.90, 2.00
        self._trades, self.completed, self.placed = [], [], []
        self.held = {}  # conId -> [qty, avgCost per contract]
        self.connect_kwargs = None

    def isConnected(self):
        return self.connected

    async def connectAsync(self, host, port, **kw):
        self.connected, self.connect_kwargs = True, dict(host=host, port=port, **kw)

    def disconnect(self):
        self.connected = False

    def managedAccounts(self):
        return self.accounts

    async def reqAllOpenOrdersAsync(self):
        return []

    def accountValues(self, account):
        return [SimpleNamespace(tag="NetLiquidation", currency="USD", value="1000000"),
                SimpleNamespace(tag="TotalCashValue", currency="USD", value="990000")]

    async def qualifyContractsAsync(self, c):
        c.conId = 777
        return [c]

    async def reqTickersAsync(self, c):
        return [SimpleNamespace(bid=self.bid, ask=self.ask, marketDataType=1)]

    def positions(self, account):
        return [SimpleNamespace(contract=SimpleNamespace(secType="OPT", symbol="SPY", lastTradeDateOrContractMonth="20261218",
                                                         right="C", strike=600.0, multiplier="100", conId=cid),
                                position=q, avgCost=cost) for cid, (q, cost) in self.held.items() if q > 0]

    def trades(self):
        return list(self._trades)

    def openTrades(self):
        return [t for t in self._trades if t.orderStatus.status not in ("Filled", "Cancelled", "Inactive")]

    async def reqCompletedOrdersAsync(self, api_only):
        return list(self.completed)

    def placeOrder(self, contract, order):
        self.placed.append(order)
        trade = SimpleNamespace(contract=contract, order=order,
                                orderStatus=SimpleNamespace(status="Submitted", filled=0, avgFillPrice=0.0))
        held = self.held.setdefault(contract.conId, [0, 0.0])
        if order.action == "BUY" and order.lmtPrice >= self.ask:
            trade.orderStatus = SimpleNamespace(status="Filled", filled=order.totalQuantity, avgFillPrice=self.ask)
            held[1] = (held[0] * held[1] + order.totalQuantity * self.ask * 100) / (held[0] + order.totalQuantity)
            held[0] += order.totalQuantity
        elif order.action == "SELL" and order.lmtPrice <= self.bid:
            trade.orderStatus = SimpleNamespace(status="Filled", filled=order.totalQuantity, avgFillPrice=self.bid)
            held[0] -= order.totalQuantity
        self._trades.append(trade)
        return trade

    def cancelOrder(self, order):
        for t in self._trades:
            if t.order is order:
                t.orderStatus.status = "Cancelled"


@pytest.fixture(autouse=True)
def paper_env(monkeypatch):
    monkeypatch.setenv("IBKR_PAPER_ACCOUNT", ACCOUNT)
    monkeypatch.setenv("IBKR_PAPER_PORT", "7497")
    monkeypatch.delenv("IBKR_HOST", raising=False)
    monkeypatch.setattr(ibkr, "SETTLE_S", 0.0)


def make(ib=None):
    return ibkr.IBKRPaperBroker(ib=ib or FakeIB(), api=FakeApi, runner=run_inline)


class TestIBKRPaperConformance(BrokerConformance):
    def make_broker(self):
        return make()

    def seed_quote(self, broker, bid, ask):
        broker._ib.bid, broker._ib.ask = bid, ask


@pytest.mark.parametrize("env,value", [("IBKR_PAPER_PORT", "7496"), ("IBKR_PAPER_PORT", "4001"),
                                       ("IBKR_HOST", "10.0.0.5"), ("IBKR_PAPER_ACCOUNT", "U1234567"),
                                       ("IBKR_PAPER_ACCOUNT", "DUxxxxxxx"), ("IBKR_PAPER_ACCOUNT", "DU 123")])
def test_refuses_live_ports_remote_hosts_and_non_paper_accounts(monkeypatch, env, value):
    monkeypatch.setenv(env, value)
    with pytest.raises(ValueError):
        make()


def test_refuses_a_session_that_also_manages_a_live_account():
    ib = FakeIB(accounts=(ACCOUNT, "U7654321"))
    broker = make(ib)
    with pytest.raises(RuntimeError):
        broker.submit_limit_order(make_intent(limit=2.50))
    assert ib.placed == [] and not ib.connected
    assert broker.healthcheck()["connected"] is False


def test_refuses_a_session_without_the_configured_account():
    ib = FakeIB(accounts=("DU0000001",))
    with pytest.raises(RuntimeError):
        make(ib).get_account()


def test_orders_are_day_limit_on_the_paper_account_tagged_with_the_key():
    ib = FakeIB()
    make(ib).submit_limit_order(make_intent(limit=2.509))
    o = ib.placed[0]
    assert (o.orderType, o.tif, o.account, o.orderRef, o.outsideRth) == ("LMT", "DAY", ACCOUNT, "optplat:key-00000001", False)
    assert o.lmtPrice == 2.50  # a buy never rounds above the approved limit
    assert ib.connect_kwargs["port"] == 7497 and ib.connect_kwargs["clientId"] == ibkr.DEFAULT_CLIENT_ID


def test_sell_limit_never_rounds_below_the_approved_limit():
    ib = FakeIB()
    broker = make(ib)
    broker.submit_limit_order(make_intent(limit=2.50))
    broker.submit_limit_order(make_intent("sell-1", limit=1.001, side=Side.SELL_TO_CLOSE))
    assert ib.placed[-1].lmtPrice == 1.01


@pytest.mark.parametrize("qty,limit", [(ibkr.MAX_CONTRACTS_PER_ORDER + 1, 0.10), (4, 13.0), (1, 0.0), (1, float("nan"))])
def test_size_and_price_ceilings(qty, limit):
    ib = FakeIB()
    with pytest.raises(BrokerRejected):
        make(ib).submit_limit_order(make_intent(qty=qty, limit=limit))
    assert ib.placed == []


def test_working_sells_count_against_what_can_be_sold():
    ib = FakeIB()
    broker = make(ib)
    broker.submit_limit_order(make_intent(limit=2.50))                                   # holds 4
    broker.submit_limit_order(make_intent("sell-a", qty=3, limit=9.00, side=Side.SELL_TO_CLOSE))  # rests
    with pytest.raises(BrokerRejected):
        broker.submit_limit_order(make_intent("sell-b", qty=2, limit=9.00, side=Side.SELL_TO_CLOSE))


def test_finds_an_order_from_an_earlier_session_in_completed_orders():
    ib = FakeIB()
    old = SimpleNamespace(contract=SimpleNamespace(conId=777),
                          order=SimpleNamespace(account=ACCOUNT, orderRef="optplat:key-00000001", totalQuantity=4, action="BUY"),
                          orderStatus=SimpleNamespace(status="Filled", filled=4, avgFillPrice=2.0))
    ib.completed.append(old)
    old.order.account = ""  # IBKR may leave it blank on completed orders from an earlier session
    broker = make(ib)
    status = broker.submit_limit_order(make_intent(limit=2.50))
    assert status.status == "FILLED" and ib.placed == []  # not sent twice


def test_lookup_failure_is_an_error_not_no_such_order():
    ib = FakeIB()

    async def broken(_api_only):
        raise ConnectionError("lost")
    ib.reqCompletedOrdersAsync = broken
    with pytest.raises(ConnectionError):
        make(ib).find_order_by_client_id("anything")


def test_quotes_are_never_marked_verified_and_delayed_data_is_refused():
    ib = FakeIB()
    broker = make(ib)
    assert broker.get_quote(CONTRACT).timestamp_verified is False

    async def delayed(_c):
        return [SimpleNamespace(bid=1.0, ask=1.1, marketDataType=3)]
    ib.reqTickersAsync = delayed
    with pytest.raises(ibkr.QuoteUnavailable):
        broker.get_quote(CONTRACT)


def test_other_accounts_orders_are_invisible():
    ib = FakeIB()
    ib._trades.append(SimpleNamespace(contract=SimpleNamespace(conId=777),
                                      order=SimpleNamespace(account="DU9999999", orderRef="optplat:key-x", totalQuantity=1, action="BUY"),
                                      orderStatus=SimpleNamespace(status="Submitted", filled=0, avgFillPrice=0.0)))
    broker = make(ib)
    assert broker.get_open_orders() == [] and broker.find_order_by_client_id("key-x") is None


# ---- account taken from TWS when IBKR_PAPER_ACCOUNT is unset (owner decision 2026-11-27)
def test_unset_account_uses_the_sessions_only_paper_account(monkeypatch):
    monkeypatch.delenv("IBKR_PAPER_ACCOUNT")
    ib = FakeIB(accounts=("DU7654321",))
    broker = make(ib)
    assert broker.account_id is None
    broker.submit_limit_order(make_intent(limit=2.50))
    assert broker.account_id == "DU7654321" and ib.placed[0].account == "DU7654321"


@pytest.mark.parametrize("accounts", [("DU1111111", "DU2222222"), ("U1234567",), ("DU1111111", "U1234567"), ()])
def test_unset_account_refuses_anything_but_exactly_one_paper_account(monkeypatch, accounts):
    monkeypatch.delenv("IBKR_PAPER_ACCOUNT")
    ib = FakeIB(accounts=accounts)
    broker = make(ib)
    with pytest.raises(RuntimeError):
        broker.submit_limit_order(make_intent(limit=2.50))
    assert ib.placed == [] and broker.account_id is None and not ib.connected


def test_connect_gets_more_time_than_ib_async_startup_needs_and_health_says_where_it_stopped():
    ib = FakeIB()
    seen = {}

    async def slow_connect(host, port, **kw):
        seen.update(kw)
        raise TimeoutError()
    ib.connectAsync = slow_connect
    h = make(ib).healthcheck()
    assert h["connected"] is False and h["failed_at"] == "connect" and h["reason"] == "TimeoutError"
    assert ibkr.CONNECT_CALL_TIMEOUT_S > 3 * ibkr.CONNECT_TIMEOUT_S  # connect + startup requests + executions
    assert seen["timeout"] == ibkr.CONNECT_TIMEOUT_S


def test_health_detail_hides_account_ids():
    ib = FakeIB()

    async def boom(host, port, **kw):
        raise ConnectionError("account DU1234567 refused")
    ib.connectAsync = boom
    assert "DU1234567" not in make(ib).healthcheck()["detail"]


# ---- the paper account is shared with the Options Alerter (2026-11-27)
@pytest.mark.parametrize("cid", sorted(ibkr.ALERTER_CLIENT_IDS))
def test_refuses_the_alerters_client_ids(monkeypatch, cid):
    monkeypatch.setenv("IBKR_ORDER_CLIENT_ID", str(cid))
    with pytest.raises(ValueError):
        ibkr.IBKRPaperBroker(ib=FakeIB(), api=FakeApi, runner=run_inline)


def test_default_client_id_is_not_the_alerters():
    assert ibkr.DEFAULT_CLIENT_ID not in ibkr.ALERTER_CLIENT_IDS and make().client_id == ibkr.DEFAULT_CLIENT_ID


def alerter_trade(ref="alerter-abc", action="BUY", qty=5, status="Filled"):
    return SimpleNamespace(contract=SimpleNamespace(conId=777),
                           order=SimpleNamespace(account=ACCOUNT, orderRef=ref, totalQuantity=qty, action=action, clientId=95),
                           orderStatus=SimpleNamespace(status=status, filled=qty if status == "Filled" else 0, avgFillPrice=2.0))


def test_alerter_orders_are_never_ours():
    ib = FakeIB()
    ib._trades.append(alerter_trade(status="Submitted"))
    ib.completed.append(alerter_trade())
    broker = make(ib)
    assert broker.get_open_orders() == [] and broker.find_order_by_client_id("alerter-abc") is None


def test_never_sells_the_alerters_contracts():
    ib = FakeIB()
    ib.held[777] = [5, 200.0]                    # the account holds 5 that the Alerter bought
    ib.completed.append(alerter_trade())
    broker = make(ib)
    with pytest.raises(BrokerRejected):
        broker.submit_limit_order(make_intent("sell-1", qty=1, limit=1.0, side=Side.SELL_TO_CLOSE))
    broker.submit_limit_order(make_intent(qty=2, limit=2.50))   # now this platform owns 2 of the 7
    broker.submit_limit_order(make_intent("sell-2", qty=2, limit=1.0, side=Side.SELL_TO_CLOSE))
    with pytest.raises(BrokerRejected):
        broker.submit_limit_order(make_intent("sell-3", qty=1, limit=1.0, side=Side.SELL_TO_CLOSE))
    assert [o.orderRef for o in ib.placed] == ["optplat:key-00000001", "optplat:sell-2"]


@pytest.mark.parametrize("acct,ok", [("DU1234567", True), ("DUH123456", True), ("DUA1B2C3D", True),
                                     ("U1234567", False), ("DF1234567", False), ("du1234567", False),
                                     ("DU12", False), ("DU 123456", False), ("XDU1234567", False), ("", False)])
def test_paper_account_ids(acct, ok):
    assert ibkr.is_paper_account(acct) is ok


def test_detects_a_paper_account_with_letters(monkeypatch):
    monkeypatch.delenv("IBKR_PAPER_ACCOUNT")
    ib = FakeIB(accounts=("DUH123456",))
    broker = make(ib)
    broker.submit_limit_order(make_intent(limit=2.50))
    assert ib.placed[0].account == "DUH123456"


def test_sells_what_an_earlier_session_bought():
    """After a restart IBKR reports our filled buy as a completed order whose orderStatus.filled is 0."""
    ib = FakeIB()
    ib.held[777] = [1, 603.0]
    ib.completed.append(SimpleNamespace(
        contract=SimpleNamespace(conId=777),
        order=SimpleNamespace(account=ACCOUNT, orderRef="optplat:buy-earlier", totalQuantity=1, action="BUY",
                              filledQuantity=1.0),
        orderStatus=SimpleNamespace(status="Filled", filled=0, avgFillPrice=0.0)))
    broker = make(ib)
    assert broker.find_order_by_client_id("buy-earlier").filled_qty == 1
    broker.submit_limit_order(make_intent("sell-now", qty=1, limit=1.0, side=Side.SELL_TO_CLOSE))
    assert ib.placed[-1].orderRef == "optplat:sell-now"


def test_unset_filled_quantity_sentinel_is_ignored():
    t = SimpleNamespace(order=SimpleNamespace(filledQuantity=1.7976931348623157e308),
                        orderStatus=SimpleNamespace(filled=2))
    assert ibkr._filled(t) == 2

