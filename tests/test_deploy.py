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

