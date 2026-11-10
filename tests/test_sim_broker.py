import pytest

from conformance import BrokerConformance
from helpers import CONTRACT, make_intent, make_quote
from optplat.broker import BrokerRejected, QuoteUnavailable, SimBroker


class TestSimBrokerConformance(BrokerConformance):
    def make_broker(self):
        return SimBroker()

    def seed_quote(self, broker, bid, ask):
        broker.set_quote(make_quote(bid, ask))


def test_missing_quote_is_rejected_not_invented():
    broker = SimBroker()
    with pytest.raises(QuoteUnavailable):
        broker.get_quote(CONTRACT)
    with pytest.raises(BrokerRejected):
        broker.submit_limit_order(make_intent())


def test_resting_order_fills_when_the_quote_comes_down():
    broker = SimBroker()
    broker.set_quote(make_quote(1.90, 2.00))
    status = broker.submit_limit_order(make_intent(limit=1.60))
    assert status.status == "SUBMITTED"
    broker.set_quote(make_quote(1.50, 1.55))
    assert broker.get_order_status(status.broker_order_id).status == "FILLED"


def test_fill_pays_ask_plus_slippage_and_reduces_cash():
    broker = SimBroker(starting_cash=10_000, slippage_pct=0.5)
    broker.set_quote(make_quote(1.90, 2.00))
    status = broker.submit_limit_order(make_intent(qty=2, limit=2.50))
    assert status.avg_fill_price == 2.01
    assert broker.get_account().cash == round(10_000 - 2.01 * 100 * 2, 2)


def test_insufficient_cash_does_not_fill():
    broker = SimBroker(starting_cash=100)
    broker.set_quote(make_quote(1.90, 2.00))
    status = broker.submit_limit_order(make_intent(qty=1, limit=2.50))
    assert status.status == "SUBMITTED" and status.filled_qty == 0
