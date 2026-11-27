from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from optplat import deploy
from optplat.api import create_app
from optplat.broker.sim import SimBroker
from optplat.orders import OrderManager
from optplat.store import Store

TOKEN = "t" * 24


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(deploy, "_last_request", 0.0)
    monkeypatch.delenv("OPTPLAT_MANAGED", raising=False)


@pytest.fixture
def client():
    with TestClient(create_app(OrderManager(SimBroker(), Store(":memory:")), TOKEN)) as c:
        yield c


def managed_root(tmp_path: Path) -> Path:
    (tmp_path / "deploy").mkdir()
    (tmp_path / "deploy" / "update.sh").write_text("#!/bin/bash\n")
    return tmp_path


def test_health_reports_a_build_id(client):
    assert client.get("/api/health").json()["build_id"]


def test_build_id_outside_a_checkout_is_unknown(tmp_path):
    assert deploy.build_id(tmp_path) == "unknown"


def test_check_on_refresh_needs_the_token(client):
    assert client.post("/api/deployment/check-on-refresh").status_code == 401


def test_unmanaged_server_never_launches_anything(tmp_path):
    calls = []
    assert deploy.request_update(managed_root(tmp_path), launch=calls.append)["status"] == "UNMANAGED"
    assert calls == []


def test_managed_server_launches_once_then_rate_limits(tmp_path, monkeypatch):
    monkeypatch.setenv("OPTPLAT_MANAGED", "1")
    root, calls = managed_root(tmp_path), []
    assert deploy.request_update(root, now=1000.0, launch=calls.append) == {"status": "QUEUED", "queued": True}
    assert deploy.request_update(root, now=1100.0, launch=calls.append)["status"] == "RECENT_CHECK_OR_IN_PROGRESS"
    assert deploy.request_update(root, now=1000.0 + deploy.MIN_INTERVAL_S, launch=calls.append)["queued"] is True
    assert len(calls) == 2 and all(c == root / "deploy" / "update.sh" for c in calls)


def test_managed_without_an_updater_script_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("OPTPLAT_MANAGED", "1")
    assert deploy.request_update(tmp_path, launch=lambda s: 1 / 0)["status"] == "UNMANAGED_NO_UPDATER"


def test_a_failed_launch_is_reported_not_raised(tmp_path, monkeypatch):
    monkeypatch.setenv("OPTPLAT_MANAGED", "1")

    def boom(_):
        raise OSError("no bash")

    assert deploy.request_update(managed_root(tmp_path), launch=boom)["status"] == "UPDATER_LAUNCH_FAILED"


def test_the_updater_only_fast_forwards_stable():
    text = (Path(deploy.ROOT) / "deploy" / "update.sh").read_text()
    assert "origin stable" in text and "--ff-only" in text and "is-ancestor" in text
    assert "--force" not in text and "push" not in text


def test_the_updater_installs_the_ibkr_extra_only_when_the_owner_switched_it_on(tmp_path):
    import subprocess
    text = (Path(deploy.ROOT) / "deploy" / "update.sh").read_text()
    assert 'pip install --quiet -e "$SPEC"' in text and ". \"$DATA/config.env\"" not in text  # read, never sourced
    start = text.index('SPEC="."')
    probe = text[start:text.index("\nfi\n", start) + 4]
    probe = probe.replace('"$APP/.venv/bin/python" -c "import ib_async"', "true")  # pretend it is installed
    for config, want in [("", "."), ("OPTPLAT_IBKR_MIRROR=1\n", ".[ibkr]"), ("export OPTPLAT_IBKR_MIRROR='1'\n", ".[ibkr]"),
                         ("OPTPLAT_BROKER=ibkr_paper\n", ".[ibkr]"), ("# OPTPLAT_IBKR_MIRROR=1\n", "."),
                         ("OPTPLAT_IBKR_MIRROR=0\n", ".")]:
        (tmp_path / "config.env").write_text(config)
        out = subprocess.run(["bash", "-c", f'DATA="{tmp_path}"; APP=/nonexistent; LABEL=x\n{probe}\necho "$SPEC"'],
                             capture_output=True, text=True, check=True).stdout.strip()
        assert out == want, (config, out)



# ---- watchdog (2026-11-27): the server once stayed down because its LaunchAgent was unloaded and nothing reloaded it.
def _watchdog(tmp_path, *, loaded, healthy, plist=True, paused=False, updating=False):
    import subprocess
    tmp_path.mkdir(parents=True, exist_ok=True)
    data, agents, calls = tmp_path / "data", tmp_path / "agents", tmp_path / "calls"
    data.mkdir(); agents.mkdir()
    if plist:
        (agents / "com.optionsplatform.server.plist").write_text("<plist/>")
    if paused:
        (data / "server-paused").write_text("")
    if updating:
        (data / "update.lock").mkdir()
    fake_lc = tmp_path / "launchctl"
    fake_lc.write_text(f'#!/bin/bash\necho "$@" >>"{calls}"\n[ "$1" = print ] && exit {0 if loaded else 113}\nexit 0\n')
    fake_curl = tmp_path / "curl"
    fake_curl.write_text(f"#!/bin/bash\nexit {0 if healthy else 7}\n")
    fake_lc.chmod(0o755); fake_curl.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "OPTPLAT_DATA_DIR": str(data), "OPTPLAT_AGENTS_DIR": str(agents),
           "OPTPLAT_LAUNCHCTL": str(fake_lc), "OPTPLAT_CURL": str(fake_curl), "OPTPLAT_WATCHDOG_WAIT_S": "0"}
    script = Path(deploy.ROOT) / "deploy" / "watchdog.sh"
    subprocess.run(["bash", str(script)], env=env, check=True, timeout=30)
    made = calls.read_text().splitlines() if calls.exists() else []
    log = (data / "watchdog.log").read_text() if (data / "watchdog.log").exists() else ""
    return [c for c in made if not c.startswith("print")], log


def test_watchdog_reloads_a_server_that_is_not_loaded(tmp_path):
    made, log = _watchdog(tmp_path, loaded=False, healthy=False)
    assert len(made) == 1 and made[0].startswith("bootstrap gui/") and made[0].endswith("com.optionsplatform.server.plist")
    assert "loaded it again" in log


def test_watchdog_restarts_a_loaded_server_that_stopped_answering(tmp_path):
    made, log = _watchdog(tmp_path, loaded=True, healthy=False)
    assert made == [m for m in made if m.startswith("kickstart -k gui/")] and len(made) == 1
    assert made[0].endswith("/com.optionsplatform.server") and "restarting it" in log


def test_watchdog_leaves_a_healthy_server_alone(tmp_path):
    made, log = _watchdog(tmp_path, loaded=True, healthy=True)
    assert made == [] and log == ""


def test_watchdog_respects_a_deliberate_pause_and_a_running_update(tmp_path):
    assert _watchdog(tmp_path / "a", loaded=False, healthy=False, paused=True)[0] == []
    assert _watchdog(tmp_path / "b", loaded=False, healthy=False, updating=True)[0] == []


def test_watchdog_without_an_install_only_says_so(tmp_path):
    made, log = _watchdog(tmp_path, loaded=False, healthy=False, plist=False)
    assert made == [] and "install_mac.sh" in log


def test_installer_adds_the_watchdog_and_never_leaves_the_server_unloaded():
    text = (Path(deploy.ROOT) / "deploy" / "install_mac.sh").read_text()
    assert "com.optionsplatform.watchdog" in text and "deploy/watchdog.sh" in text and "<integer>300</integer>" in text
    assert text.index("trap reload_server EXIT") < text.index('launchctl bootout "gui/$(id -u)/com.optionsplatform.server"')
    launcher = (Path(deploy.ROOT) / "start-platform.command").read_text()
    assert launcher.index("com.optionsplatform.server.plist") < launcher.index(".venv/bin/python -m optplat")


# ---- export setup script (2026-11-27): one command instead of five manual steps; private only, idempotent.
def _setup_export(tmp_path, *, private="true", existing=False, preset=""):
    import subprocess
    tmp_path.mkdir(parents=True, exist_ok=True)
    data, app, calls = tmp_path / "data", tmp_path / "app", tmp_path / "calls"
    (app / "deploy").mkdir(parents=True); data.mkdir()
    (app / "deploy" / "export_push.sh").write_text(f'#!/bin/bash\necho ran >>"{calls}"\n')
    if preset:
        (data / "config.env").write_text(preset)
    gh = tmp_path / "gh"
    gh.write_text(f'''#!/bin/bash
echo "gh $@" >>"{calls}"
case "$1 $2" in
 "auth status") exit 0;; "api user") echo alice;;
 "repo view") if echo "$@" | grep -q isPrivate; then echo {private}; else exit {0 if existing else 1}; fi;;
 "repo create") exit 0;;
esac
''')
    gh.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "OPTPLAT_DATA_DIR": str(data), "OPTPLAT_APP_DIR": str(app), "OPTPLAT_GH": str(gh)}
    script = Path(deploy.ROOT) / "deploy" / "setup_export.sh"
    r = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
    cfg = (data / "config.env").read_text() if (data / "config.env").exists() else ""
    return r, cfg, calls.read_text() if calls.exists() else ""


def test_setup_export_creates_a_private_repo_writes_config_and_exports(tmp_path):
    r, cfg, calls = _setup_export(tmp_path)
    assert r.returncode == 0 and "repo create alice/options-platform-data --private" in calls
    assert cfg == "OPTPLAT_EXPORT_REPO=https://github.com/alice/options-platform-data.git\n" and calls.rstrip().endswith("ran")


def test_setup_export_refuses_a_repo_that_is_not_private(tmp_path):
    r, cfg, calls = _setup_export(tmp_path, private="false", existing=True)
    assert r.returncode == 1 and "NOT private" in r.stdout and cfg == "" and "ran" not in calls


def test_setup_export_is_idempotent_and_keeps_an_existing_setting(tmp_path):
    r, cfg, calls = _setup_export(tmp_path, existing=True, preset="OPTPLAT_EXPORT_REPO=https://github.com/alice/other.git\n")
    assert r.returncode == 0 and "repo create" not in calls and cfg.count("OPTPLAT_EXPORT_REPO") == 1 and "other.git" in cfg


def test_server_wrapper_passes_plain_and_exported_config_lines_to_the_server(tmp_path):
    """Run the real wrapper with a stub python: a plain KEY=value line in config.env must reach the server's environment."""
    import os, subprocess
    home = tmp_path / "home"
    data = home / "Library" / "Application Support" / "OptionsPlatform"
    app = home / "Applications" / "OptionsPlatform" / ".venv" / "bin"
    data.mkdir(parents=True)
    app.mkdir(parents=True)
    (data / "config.env").write_text("OPTPLAT_API_TOKEN=plain-token-1234567890\nOPTPLAT_MAX_POSITION_PCT=35\nexport OPTPLAT_IBKR_MIRROR=1\n")
    out = tmp_path / "env.txt"
    (app / "python").write_text(f'#!/bin/bash\nenv | grep ^OPTPLAT_ > "{out}"\n')
    (app / "python").chmod(0o755)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin"}
    r = subprocess.run(["bash", os.path.join(root, "deploy", "server-wrapper.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = out.read_text()
    assert "OPTPLAT_MAX_POSITION_PCT=35" in got and "OPTPLAT_API_TOKEN=plain-token-1234567890" in got and "OPTPLAT_IBKR_MIRROR=1" in got
