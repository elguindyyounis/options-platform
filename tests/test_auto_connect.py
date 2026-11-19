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
