"""Run the local API:  python -m optplat"""
from __future__ import annotations

import os
import sys

import uvicorn

from .api import create_app
from .broker.sim import SimBroker
from .orders import OrderManager
from .store import Store


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

    store = Store(os.environ.get("OPTPLAT_DB", "optplat.db"))
    manager = OrderManager(broker, store)
    # Bound to localhost only. Do not expose this server to the internet.
    uvicorn.run(create_app(manager, token), host="127.0.0.1", port=int(os.environ.get("OPTPLAT_PORT", "8800")))


if __name__ == "__main__":
    main()
