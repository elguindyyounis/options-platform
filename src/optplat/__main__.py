"""Run the local API:  python -m optplat"""
from __future__ import annotations

import os
import sys

import uvicorn

from .api import create_app
from .broker.sim import SimBroker
from .engine import EngineConfig, Runner, TradingEngine
from .marketdata import DemoDataProvider, YahooDataProvider
from .orders import OrderManager
from .risk import RiskPolicy
from .store import Store
from .strategy import LiquidTrendStrategy


def main() -> None:
    token = os.environ.get("OPTPLAT_API_TOKEN", "")
    if len(token) < 16:
        sys.exit("Set OPTPLAT_API_TOKEN to a random string of at least 16 characters (see .env.example).")

    which = os.environ.get("OPTPLAT_BROKER", "sim")
    if which == "sim":
        broker = SimBroker()
    elif which == "ibkr_paper":
        from .broker.ibkr import IBKRPaperBroker

        broker = IBKRPaperBroker()
    else:
        sys.exit("OPTPLAT_BROKER must be 'sim' or 'ibkr_paper'")

    data = os.environ.get("OPTPLAT_DATA", "demo" if which == "sim" else "yahoo")
    if data == "demo":
        provider = DemoDataProvider()
    elif data == "yahoo":
        provider = YahooDataProvider()
    else:
        sys.exit("OPTPLAT_DATA must be 'demo' or 'yahoo'")

    # Unofficial quotes carry no verified timestamp; the safe default rejects them. Allowing them is an
    # explicit, visible choice.
    allow_unverified = os.environ.get("OPTPLAT_ALLOW_UNVERIFIED_QUOTES") == "1"
    policy = RiskPolicy(require_verified_quote_time=not allow_unverified)

    store = Store(os.environ.get("OPTPLAT_DB", "optplat.db"))
    manager = OrderManager(broker, store, policy)
    # The demo market is fictional and runs at any hour, so market-hours enforcement is off by default there.
    default_cfg = EngineConfig(enforce_market_hours=(data != "demo"))
    engine = TradingEngine(manager, provider, LiquidTrendStrategy(), default_config=default_cfg)
    runner = Runner(engine)
    # Bound to localhost only. Do not expose this server to the internet.
    uvicorn.run(
        create_app(manager, token, engine, runner),
        host="127.0.0.1",
        port=int(os.environ.get("OPTPLAT_PORT", "8800")),
    )


if __name__ == "__main__":
    main()
