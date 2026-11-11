"""Run the local API:  python -m optplat"""
from __future__ import annotations

import os
import re
import secrets
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from .api import create_app
from .broker.sim import SimBroker
from .engine import EngineConfig, Runner, TradingEngine
from .marketdata import DemoDataProvider, YahooDataProvider
from .orders import OrderManager
from .risk import RiskPolicy
from .store import Store
from .strategy import LiquidTrendStrategy


_FRAGMENT_SAFE_TOKEN = re.compile(r"[A-Za-z0-9_-]{16,200}")


def _open_when_ready(url: str, port: int, timeout_s: float = 15.0) -> None:
    """Open the dashboard once the server accepts connections (best effort, never raises)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.2)
    else:
        return
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - a missing browser must not stop the server
        pass


def _start_browser_opener(url: str, port: int) -> None:
    threading.Thread(target=_open_when_ready, args=(url, port), name="optplat-open-browser", daemon=True).start()


def main() -> None:
    token = os.environ.get("OPTPLAT_API_TOKEN", "")
    if not token:
        # Show the one-off token in the terminal that started the server, so it can be pasted into the dashboard.
        token = secrets.token_urlsafe(32)
        print(
            "\nNo OPTPLAT_API_TOKEN was set, so a one-off token was generated for this run.\n"
            f"Paste it into the dashboard:\n\n    {token}\n",
            flush=True,
        )
    elif len(token) < 16:
        sys.exit("OPTPLAT_API_TOKEN must be at least 16 characters (or leave it unset to get a generated one).")

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
    from .events import EventCalendar, yahoo_earnings_dates

    calendar = EventCalendar(earnings_source=yahoo_earnings_dates if data == "yahoo" else None)
    engine = TradingEngine(manager, provider, LiquidTrendStrategy(), default_config=default_cfg, calendar=calendar)
    scan_every = os.environ.get("OPTPLAT_SCAN_EVERY_S", "")
    if scan_every:
        try:
            engine.set_config({"scan_interval_s": int(scan_every)})
        except ValueError:
            sys.exit("OPTPLAT_SCAN_EVERY_S must be 0 or a number of seconds from 600 to 86400")
    mode = os.environ.get("OPTPLAT_COMMITTEE", "")
    if mode:
        if mode not in ("off", "shadow", "active"):
            sys.exit("OPTPLAT_COMMITTEE must be off, shadow or active")
        engine.set_config({"committee_mode": mode})  # saved with the other settings; the dashboard can change it later
    runner = Runner(engine)
    port = int(os.environ.get("OPTPLAT_PORT", "8800"))
    dashboard = f"http://127.0.0.1:{port}"
    print(f"Dashboard: {dashboard}   broker={which}   data={data}", flush=True)
    if data == "demo":
        print("NOTE: demo data is FICTIONAL random prices. Profit or loss here means nothing.", flush=True)
    if allow_unverified:
        print("WARNING: unverified, delayed quotes are allowed through the risk gate. Research only.", flush=True)
    if os.environ.get("OPTPLAT_AUTOSTART_LOOP") == "1":
        # Starts the cycle loop only. Automatic entries stay exactly as saved (off unless the owner turned them on).
        runner.start()
        entries = "ON" if engine.config().auto_entries else "off"
        print(f"Loop started automatically. Automatic entries: {entries} (saved setting).", flush=True)
    if os.environ.get("OPTPLAT_OPEN_BROWSER") == "1":
        # The token travels in the URL fragment, which browsers never send to the server. The dashboard reads it
        # once and removes it from the address bar. Tokens with unusual characters are not put in a URL.
        url = f"{dashboard}/#token={token}" if _FRAGMENT_SAFE_TOKEN.fullmatch(token) else dashboard
        _start_browser_opener(url, port)
    # Bound to localhost only. Do not expose this server to the internet.
    uvicorn.run(create_app(manager, token, engine, runner), host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
