"""Local HTTP API. There is deliberately no live-trading endpoint."""
from __future__ import annotations

import hmac
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .broker.sim import SimBroker
from .models import OptionContract, OrderIntent, Quote, Right, utcnow
from .orders import InvalidTransition, LiveTradingDisabled, OrderManager

SYMBOL = r"^[A-Z][A-Z0-9.\-]{0,9}$"


class ContractBody(BaseModel):
    underlying: str = Field(pattern=SYMBOL)
    expiry: date
    right: Right
    strike: float = Field(gt=0, lt=100_000)

    def to_contract(self) -> OptionContract:
        return OptionContract(self.underlying, self.expiry, self.right, self.strike)


class OrderBody(ContractBody):
    idempotency_key: str = Field(min_length=8, max_length=64)
    candidate_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=100)
    limit_price: float = Field(gt=0, lt=100_000)
    note: str = Field(default="", max_length=200)


class KillSwitchBody(BaseModel):
    active: bool
    reason: str = Field(default="", max_length=200)


class SimQuoteBody(ContractBody):
    bid: float = Field(ge=0)
    ask: float = Field(gt=0)


def create_app(manager: OrderManager, api_token: str) -> FastAPI:
    if not api_token or len(api_token) < 16:
        raise ValueError("api_token must be at least 16 characters")
    app = FastAPI(title="options-platform", docs_url=None, redoc_url=None)

    def auth(x_api_token: str = Header(default="")) -> None:
        if not hmac.compare_digest(x_api_token.encode(), api_token.encode()):
            raise HTTPException(status_code=401, detail="Invalid or missing API token")

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        try:
            broker = manager.broker.healthcheck()
        except Exception as exc:  # noqa: BLE001
            broker = {"connected": False, "error": type(exc).__name__}
        return {"ok": True, "mode": manager.broker.mode.value, "broker": broker}

    @app.get("/api/portfolio", dependencies=[Depends(auth)])
    def portfolio() -> dict[str, Any]:
        return manager.portfolio()

    @app.get("/api/paper/orders", dependencies=[Depends(auth)])
    def list_orders(open_only: bool = False) -> list[dict[str, Any]]:
        return [o.to_dict() for o in manager.list(open_only=open_only)]

    @app.post("/api/paper/orders", dependencies=[Depends(auth)])
    def submit_order(body: OrderBody) -> dict[str, Any]:
        intent = OrderIntent(
            idempotency_key=body.idempotency_key,
            candidate_id=body.candidate_id,
            contract=body.to_contract(),
            quantity=body.quantity,
            limit_price=body.limit_price,
            note=body.note,
        )
        try:
            return manager.submit_buy(intent).to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except LiveTradingDisabled as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/paper/orders/{order_id}/cancel", dependencies=[Depends(auth)])
    def cancel_order(order_id: str) -> dict[str, Any]:
        try:
            return manager.cancel(order_id).to_dict()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Order not found") from exc
        except InvalidTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/paper/reconcile", dependencies=[Depends(auth)])
    def reconcile() -> dict[str, Any]:
        return {"changed": manager.reconcile()}

    @app.post("/api/risk/kill-switch", dependencies=[Depends(auth)])
    def kill_switch(body: KillSwitchBody) -> dict[str, Any]:
        manager.set_kill_switch(body.active, body.reason)
        return {"kill_switch": manager.kill_switch_active()}

    @app.get("/api/risk/policy", dependencies=[Depends(auth)])
    def policy() -> dict[str, Any]:
        return manager.policy.to_dict()

    if isinstance(manager.broker, SimBroker):
        sim: SimBroker = manager.broker

        @app.post("/api/sim/quote", dependencies=[Depends(auth)])
        def set_sim_quote(body: SimQuoteBody) -> dict[str, Any]:
            if body.bid > body.ask:
                raise HTTPException(status_code=422, detail="bid must not exceed ask")
            sim.set_quote(
                Quote(body.to_contract(), body.bid, body.ask, utcnow(), "sim", timestamp_verified=True)
            )
            return {"ok": True}

    return app
