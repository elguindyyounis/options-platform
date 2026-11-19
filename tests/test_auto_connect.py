import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "src/optplat/static/app.js").read_text()


def test_token_is_remembered_across_tabs_and_dropped_when_rejected():
    assert 'localStorage.setItem(TOKEN_KEY' in APP_JS and 'localStorage.getItem(TOKEN_KEY' in APP_JS
    assert re.search(r"status === 401 \|\| e\.status === 403\) \{ forgetToken\(\)", APP_JS)  # a stale token is not retried forever
    assert 'addEventListener("hashchange", () => { if (takeTokenFromUrl())' in APP_JS  # a tokened link pasted into an open tab works


def test_token_still_travels_only_in_the_fragment_and_header():
    assert "location.search" not in APP_JS.split("function takeTokenFromUrl")[0]
    assert "history.replaceState(null" in APP_JS  # removed from the address bar after it is read


def test_shell_scripts_parse_and_installer_links_use_the_fragment():
    for f in ("deploy/install_mac.sh", "start-platform.command", "Install-On-Mac.command"):
        assert subprocess.run(["bash", "-n", str(ROOT / f)]).returncode == 0, f
    install = (ROOT / "deploy/install_mac.sh").read_text()
    assert "#token=%s" in install and "grep -Eq '^[A-Za-z0-9_-]{16,200}$'" in install  # odd tokens are never put in a URL
    assert "chmod 600" in (ROOT / "start-platform.command").read_text()


def _client(**kw):
    from fastapi.testclient import TestClient

    from optplat.api import create_app
    from optplat.broker import SimBroker
    from optplat.engine import EngineConfig, TradingEngine
    from optplat.marketdata import DemoDataProvider
    from optplat.orders import OrderManager
    from optplat.store import Store
    from optplat.strategy import LiquidTrendStrategy

    manager = OrderManager(SimBroker(), Store(":memory:"))
    engine = TradingEngine(manager, DemoDataProvider(), LiquidTrendStrategy(), default_config=EngineConfig())
    return TestClient(create_app(manager, "t" * 24, engine, None, **kw), base_url="http://127.0.0.1")


PAGE = {"X-Optplat-Page": "1"}


def test_session_hands_token_only_to_this_machines_own_page():
    with _client(local_clients=("testclient",)) as c:
        assert c.get("/api/session", headers=PAGE).json() == {"token": "t" * 24}
        assert c.get("/api/session").status_code == 403  # no custom header: a cross-site page cannot send one without a preflight
        assert c.get("/api/session", headers={**PAGE, "Sec-Fetch-Site": "cross-site"}).status_code == 403
        assert c.get("/api/session", headers={**PAGE, "Origin": "http://evil.example"}).status_code == 403
        assert c.get("/api/session", headers={**PAGE, "Origin": "http://127.0.0.1"}).status_code == 200
        assert c.get("/api/session", headers={**PAGE, "Host": "evil.example"}).status_code == 400  # DNS-rebinding check still applies


def test_session_refused_from_another_machine_or_when_switched_off():
    with _client() as c:  # the test client is not 127.0.0.1, so it counts as another machine
        assert c.get("/api/session", headers=PAGE).status_code == 403
    with _client(local_autoconnect=False, local_clients=("testclient",)) as c:
        assert c.get("/api/session", headers=PAGE).status_code == 403


def test_every_other_route_still_needs_the_token():
    with _client(local_clients=("testclient",)) as c:
        assert c.get("/api/portfolio").status_code == 401
        assert c.get("/api/shadow").status_code == 401
        assert c.post("/api/risk/kill-switch", json={}).status_code == 401
