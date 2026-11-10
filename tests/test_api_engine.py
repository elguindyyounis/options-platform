from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from optplat.api import create_app
from optplat.broker import SimBroker
from optplat.engine import EngineConfig, Runner, TradingEngine
from optplat.marketdata import DemoDataProvider
from optplat.orders import OrderManager
from optplat.store import Store
from optplat.strategy import LiquidTrendStrategy

TOKEN = "t" * 24
H = {"X-API-Token": TOKEN}


@pytest.fixture
def client():
    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    runner = Runner(engine)
    app = create_app(manager, TOKEN, engine, runner)
    with TestClient(app) as c:
        yield c
    runner.stop()


def test_dashboard_is_served_with_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200 and "options-platform" in r.text
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    js = client.get("/static/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]


def test_dashboard_never_assigns_html_from_api_data(client):
    src = client.get("/static/app.js").text
    assert "innerHTML" not in src and "outerHTML" not in src and "insertAdjacentHTML" not in src


def test_dashboard_reads_a_launcher_token_from_the_fragment_and_scrubs_it(client):
    src = client.get("/static/app.js").text
    assert "location.hash" in src and "history.replaceState" in src


def test_unexpected_host_header_is_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400


def test_engine_endpoints_require_the_token(client):
    for method, path in [("get", "/api/engine/status"), ("post", "/api/engine/cycle"),
                         ("put", "/api/engine/config"), ("get", "/api/report"),
                         ("post", "/api/engine/start"), ("post", "/api/engine/stop")]:
        assert getattr(client, method)(path).status_code == 401, path


def test_status_and_config_round_trip(client):
    status = client.get("/api/engine/status", headers=H).json()
    assert status["config"]["auto_entries"] is False
    assert status["data_source"] == {"name": "demo-synthetic", "fictional": True}
    r = client.put("/api/engine/config", json={"watchlist": ["spy", "qqq"], "auto_entries": True}, headers=H)
    assert r.status_code == 200 and r.json()["watchlist"] == ["SPY", "QQQ"] and r.json()["auto_entries"] is True


def test_invalid_config_is_422(client):
    r = client.put("/api/engine/config", json={"auto_entries": True, "auto_exits": False}, headers=H)
    assert r.status_code == 422 and "auto_exits" in r.json()["detail"]
    assert client.put("/api/engine/config", json={"watchlist": ["bad ticker!"]}, headers=H).status_code == 422


def test_run_cycle_and_loop_controls(client):
    client.put("/api/engine/config", json={"enforce_market_hours": False, "auto_entries": True}, headers=H)
    report = client.post("/api/engine/cycle", headers=H).json()
    assert {"exits", "entries", "errors", "market_open"} <= set(report)
    assert any(e.get("result") == "FILLED" for e in report["entries"])  # demo market is tradable
    assert client.post("/api/engine/start", headers=H).json()["running"] is True
    assert client.post("/api/engine/stop", headers=H).json()["running"] is False
    assert client.get("/api/portfolio", headers=H).json()["positions"]


def test_buy_then_sell_through_the_api_updates_the_report(client):
    expiry = (date.today() + timedelta(days=40)).isoformat()
    contract = {"underlying": "SPY", "expiry": expiry, "right": "C", "strike": 600}
    assert client.post("/api/sim/quote", json={**contract, "bid": 1.90, "ask": 2.00}, headers=H).status_code == 200
    buy = client.post("/api/paper/orders", headers=H, json={
        **contract, "idempotency_key": "api-buy-0001", "candidate_id": "t", "quantity": 4, "limit_price": 2.02}).json()
    assert buy["state"] == "FILLED"
    sell = client.post("/api/paper/orders", headers=H, json={
        **contract, "idempotency_key": "api-sell-0001", "candidate_id": "t", "quantity": 4,
        "limit_price": 1.85, "side": "SELL_TO_CLOSE"}).json()
    assert sell["state"] == "FILLED" and sell["cost_basis"] == 2.01
    report = client.get("/api/report", headers=H).json()
    assert report["closed_trades"] == 1 and report["open"] == []


def test_selling_without_a_position_is_rejected_not_errored(client):
    expiry = (date.today() + timedelta(days=40)).isoformat()
    contract = {"underlying": "SPY", "expiry": expiry, "right": "C", "strike": 600}
    client.post("/api/sim/quote", json={**contract, "bid": 1.90, "ask": 2.00}, headers=H)
    r = client.post("/api/paper/orders", headers=H, json={
        **contract, "idempotency_key": "api-sell-0002", "candidate_id": "t", "quantity": 1,
        "limit_price": 1.85, "side": "SELL_TO_CLOSE"})
    assert r.status_code == 200 and r.json()["state"] == "RISK_REJECTED"


def test_status_exposes_recorder_counts_and_config_accepts_retention(client):
    r = client.get("/api/engine/status", headers=H).json()
    assert r["recorder"]["total"] == 0 and r["config"]["record_snapshots"] is True
    ok = client.put("/api/engine/config", json={"snapshot_retention_days": 7}, headers=H)
    assert ok.status_code == 200 and ok.json()["snapshot_retention_days"] == 7
    bad = client.put("/api/engine/config", json={"snapshot_retention_days": 0}, headers=H)
    assert bad.status_code == 422 or bad.status_code == 400
