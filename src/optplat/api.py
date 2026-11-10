"""Local HTTP API. There is deliberately no live-trading endpoint."""
from __future__ import annotations

import hmac
from datetime import date
from typing import Any

from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .broker.sim import SimBroker
from .engine import Runner, TradingEngine
from .models import OptionContract, OrderIntent, Quote, Right, Side, utcnow
from .orders import InvalidTransition, LiveTradingDisabled, OrderManager

STATIC_DIR = Path(__file__).parent / "static"

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
    side: Side = Side.BUY_TO_OPEN


class EngineConfigBody(BaseModel):
    watchlist: Optional[list[str]] = None
    auto_entries: Optional[bool] = None
    auto_exits: Optional[bool] = None
    max_new_per_cycle: Optional[int] = None
    order_ttl_s: Optional[int] = None
    interval_s: Optional[int] = None
    enforce_market_hours: Optional[bool] = None
    take_profit_pct: Optional[float] = None
    stop_loss_pct: Optional[float] = None
    max_days_held: Optional[int] = None
    min_dte_to_hold: Optional[int] = None
    reentry_cooldown_s: Optional[int] = None


class KillSwitchBody(BaseModel):
    active: bool
    reason: str = Field(default="", max_length=200)


class SimQuoteBody(ContractBody):
    bid: float = Field(ge=0)
    ask: float = Field(gt=0)


def create_app(
    manager: OrderManager,
    api_token: str,
    engine: Optional[TradingEngine] = None,
    runner: Optional[Runner] = None,
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "testserver"),
) -> FastAPI:
    if not api_token or len(api_token) < 16:
        raise ValueError("api_token must be at least 16 characters")
    app = FastAPI(title="options-platform", docs_url=None, redoc_url=None)
    # Reject unexpected Host headers (DNS-rebinding protection for a localhost service).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(allowed_hosts))

    @app.middleware("http")
    async def security_headers(request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
        )
        return response

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    @app.get("/static/app.js", include_in_schema=False)
    def dashboard_js() -> FileResponse:
        return FileResponse(STATIC_DIR / "app.js", media_type="text/javascript")

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
            side=body.side,
        )
        try:
            return manager.submit(intent).to_dict()
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

    @app.get("/api/report", dependencies=[Depends(auth)])
    def report() -> dict[str, Any]:
        return manager.report()

    if engine is not None:

        @app.get("/api/engine/status", dependencies=[Depends(auth)])
        def engine_status() -> dict[str, Any]:
            return {**engine.status(), "runner": runner.status() if runner else {"running": False}}

        @app.put("/api/engine/config", dependencies=[Depends(auth)])
        def engine_config(body: EngineConfigBody) -> dict[str, Any]:
            try:
                return engine.set_config(body.model_dump(exclude_none=True)).to_dict()
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        @app.post("/api/engine/cycle", dependencies=[Depends(auth)])
        def engine_cycle() -> dict[str, Any]:
            return engine.run_cycle()

        if runner is not None:

            @app.post("/api/engine/start", dependencies=[Depends(auth)])
            def engine_start() -> dict[str, Any]:
                runner.start()
                return runner.status()

            @app.post("/api/engine/stop", dependencies=[Depends(auth)])
            def engine_stop() -> dict[str, Any]:
                runner.stop()
                return runner.status()

    return app
