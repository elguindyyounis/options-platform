import pytest
from fastapi.testclient import TestClient

from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.orders import OrderManager
from optplat.store import Store

TOKEN = "t" * 24
HEADERS = {"X-API-Token": TOKEN}


def order_body(key="api-key-0001", qty=4, limit=2.05):
    return {
        "idempotency_key": key,
        "candidate_id": "cand-1",
        "underlying": "SPY",
        "expiry": "2026-12-18",
        "right": "C",
        "strike": 600,
        "quantity": qty,
        "limit_price": limit,
    }


@pytest.fixture
def client():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    return TestClient(create_app(manager, TOKEN))


def test_health_is_open_but_reports_paper_mode(client):
    body = client.get("/api/health").json()
    assert body["ok"] and body["mode"] == "PAPER"


def test_other_endpoints_require_the_token(client):
    assert client.get("/api/portfolio").status_code == 401
    assert client.post("/api/paper/orders", json=order_body()).status_code == 401
    assert client.get("/api/portfolio", headers={"X-API-Token": "wrong"}).status_code == 401


def test_weak_token_is_refused_at_startup():
    with pytest.raises(ValueError):
        create_app(OrderManager(SimBroker(), Store(":memory:")), "short")


def test_order_without_quote_is_risk_rejected(client):
    r = client.post("/api/paper/orders", json=order_body(), headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["state"] == "RISK_REJECTED"


def test_invalid_payloads_are_422(client):
    assert client.post("/api/paper/orders", json=order_body(qty=0), headers=HEADERS).status_code == 422
    bad = order_body()
    bad["underlying"] = "spy; drop"
    assert client.post("/api/paper/orders", json=bad, headers=HEADERS).status_code == 422


def test_idempotent_submit_and_conflict(client):
    first = client.post("/api/paper/orders", json=order_body(), headers=HEADERS).json()
    again = client.post("/api/paper/orders", json=order_body(), headers=HEADERS).json()
    assert first["id"] == again["id"]
    conflict = client.post("/api/paper/orders", json=order_body(qty=2), headers=HEADERS)
    assert conflict.status_code == 409


def test_kill_switch_endpoint(client):
    r = client.post("/api/risk/kill-switch", json={"active": True, "reason": "test"}, headers=HEADERS)
    assert r.json() == {"kill_switch": True}
    assert client.get("/api/portfolio", headers=HEADERS).json()["kill_switch"] is True


def test_cancel_unknown_order_is_404(client):
    assert client.post("/api/paper/orders/nope/cancel", headers=HEADERS).status_code == 404
