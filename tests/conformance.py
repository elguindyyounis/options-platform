"""Shared behavioural tests every BrokerAdapter must pass.

Subclass ``BrokerConformance`` in your own test module, override the hooks, and pytest will run
these against your adapter. Hooks that seed quotes can be no-ops for a real paper broker if you
choose contracts and prices that are live in the market (run during market hours).
"""
from __future__ import annotations

import pytest

from helpers import CONTRACT, make_intent, make_quote
from optplat.broker import BrokerRejected
from optplat.models import Mode, Side


class BrokerConformance:
    # ---- hooks to override -------------------------------------------
    def make_broker(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def seed_quote(self, broker, bid: float, ask: float) -> None:  # pragma: no cover
        raise NotImplementedError

    # ---- tests --------------------------------------------------------
    def test_mode_is_paper(self):
        assert self.make_broker().mode is Mode.PAPER

    def test_healthcheck_reports_connection(self):
        health = self.make_broker().healthcheck()
        assert "connected" in health

    def test_marketable_limit_fills_and_updates_positions(self):
        broker = self.make_broker()
        self.seed_quote(broker, 1.90, 2.00)
        status = broker.submit_limit_order(make_intent(limit=2.50))
        assert status.status == "FILLED"
        assert status.filled_qty == 4 and status.avg_fill_price > 0
        assert [p.contract for p in broker.get_positions()] == [CONTRACT]

    def test_limit_below_ask_does_not_fill_and_can_be_cancelled(self):
        broker = self.make_broker()
        self.seed_quote(broker, 1.90, 2.00)
        status = broker.submit_limit_order(make_intent(limit=1.00))
        assert status.status == "SUBMITTED" and status.filled_qty == 0
        assert broker.get_positions() == []
        cancelled = broker.cancel_order(status.broker_order_id)
        assert cancelled.status == "CANCELLED"

    def test_submit_is_idempotent_on_client_id(self):
        broker = self.make_broker()
        self.seed_quote(broker, 1.90, 2.00)
        first = broker.submit_limit_order(make_intent(limit=1.00))
        second = broker.submit_limit_order(make_intent(limit=1.00))
        assert first.broker_order_id == second.broker_order_id
        assert len(broker.get_open_orders()) == 1

    def test_find_order_by_client_id(self):
        broker = self.make_broker()
        self.seed_quote(broker, 1.90, 2.00)
        placed = broker.submit_limit_order(make_intent(limit=1.00))
        found = broker.find_order_by_client_id("key-00000001")
        assert found is not None and found.broker_order_id == placed.broker_order_id
        assert broker.find_order_by_client_id("never-sent") is None

    def test_sell_to_close_fills_and_reduces_the_position(self):
        broker = self.make_broker()
        self.seed_quote(broker, 1.90, 2.00)
        broker.submit_limit_order(make_intent(limit=2.50))
        sell = broker.submit_limit_order(make_intent("sell-00000001", limit=1.00, side=Side.SELL_TO_CLOSE))
        assert sell.status == "FILLED" and sell.filled_qty == 4
        assert broker.get_positions() == []

    def test_cannot_sell_what_is_not_held(self):
        broker = self.make_broker()
        self.seed_quote(broker, 1.90, 2.00)
        with pytest.raises(BrokerRejected):
            broker.submit_limit_order(make_intent("sell-00000002", side=Side.SELL_TO_CLOSE))

    def test_sell_is_idempotent_on_client_id(self):
        broker = self.make_broker()
        self.seed_quote(broker, 1.90, 2.00)
        broker.submit_limit_order(make_intent(limit=2.50))
        a = broker.submit_limit_order(make_intent("sell-00000003", limit=5.00, side=Side.SELL_TO_CLOSE))
        b = broker.submit_limit_order(make_intent("sell-00000003", limit=5.00, side=Side.SELL_TO_CLOSE))
        assert a.broker_order_id == b.broker_order_id

    def test_account_fields_are_present(self):
        account = self.make_broker().get_account()
        assert account.equity > 0 and account.cash >= 0 and account.open_premium >= 0
