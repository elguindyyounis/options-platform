import pytest

import optplat.__main__ as entry


@pytest.fixture(autouse=True)
def quiet_env(monkeypatch):
    monkeypatch.setenv("OPTPLAT_DB", ":memory:")
    monkeypatch.setenv("OPTPLAT_BROKER", "sim")
    monkeypatch.setenv("OPTPLAT_DATA", "demo")
    monkeypatch.delenv("OPTPLAT_ALLOW_UNVERIFIED_QUOTES", raising=False)


def test_missing_token_is_generated_and_shown_so_it_can_be_pasted(monkeypatch, capsys):
    monkeypatch.delenv("OPTPLAT_API_TOKEN", raising=False)
    captured = {}
    monkeypatch.setattr(entry, "create_app", lambda manager, token, engine, runner: captured.setdefault("token", token))
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: None)
    entry.main()
    out = capsys.readouterr().out
    assert len(captured["token"]) >= 32 and captured["token"] in out
    assert "FICTIONAL" in out and "Dashboard: http://127.0.0.1:" in out


def test_each_run_gets_a_different_generated_token(monkeypatch):
    monkeypatch.delenv("OPTPLAT_API_TOKEN", raising=False)
    tokens = []
    monkeypatch.setattr(entry, "create_app", lambda manager, token, engine, runner: tokens.append(token))
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: None)
    entry.main()
    entry.main()
    assert len(set(tokens)) == 2


def test_a_weak_supplied_token_is_still_refused(monkeypatch):
    monkeypatch.setenv("OPTPLAT_API_TOKEN", "short")
    with pytest.raises(SystemExit):
        entry.main()


def test_unverified_quote_opt_in_is_announced_loudly(monkeypatch, capsys):
    monkeypatch.setenv("OPTPLAT_API_TOKEN", "x" * 24)
    monkeypatch.setenv("OPTPLAT_ALLOW_UNVERIFIED_QUOTES", "1")
    monkeypatch.setattr(entry, "create_app", lambda *a, **k: None)
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: None)
    entry.main()
    assert "WARNING: unverified" in capsys.readouterr().out


def _stub_server(monkeypatch):
    monkeypatch.setattr(entry, "create_app", lambda *a, **k: None)
    monkeypatch.setattr(entry.uvicorn, "run", lambda *a, **k: None)


def test_browser_is_not_opened_and_loop_not_started_by_default(monkeypatch):
    monkeypatch.setenv("OPTPLAT_API_TOKEN", "x" * 24)
    monkeypatch.delenv("OPTPLAT_OPEN_BROWSER", raising=False)
    monkeypatch.delenv("OPTPLAT_AUTOSTART_LOOP", raising=False)
    _stub_server(monkeypatch)
    opened, started = [], []
    monkeypatch.setattr(entry, "_start_browser_opener", lambda url, port: opened.append(url))
    monkeypatch.setattr(entry.Runner, "start", lambda self: started.append(1))
    entry.main()
    assert opened == [] and started == []


def test_open_browser_puts_the_token_in_the_url_fragment_only(monkeypatch):
    monkeypatch.setenv("OPTPLAT_API_TOKEN", "abcdEFGH1234_-xyz" * 2)
    monkeypatch.setenv("OPTPLAT_OPEN_BROWSER", "1")
    monkeypatch.setenv("OPTPLAT_PORT", "8899")
    _stub_server(monkeypatch)
    opened = []
    monkeypatch.setattr(entry, "_start_browser_opener", lambda url, port: opened.append((url, port)))
    entry.main()
    assert opened == [("http://127.0.0.1:8899/#token=" + "abcdEFGH1234_-xyz" * 2, 8899)]


def test_a_token_with_unusual_characters_is_never_put_in_a_url(monkeypatch):
    monkeypatch.setenv("OPTPLAT_API_TOKEN", "has space & symbols !!!!")
    monkeypatch.setenv("OPTPLAT_OPEN_BROWSER", "1")
    _stub_server(monkeypatch)
    opened = []
    monkeypatch.setattr(entry, "_start_browser_opener", lambda url, port: opened.append(url))
    entry.main()
    assert opened and "#token" not in opened[0]


def test_autostart_starts_the_loop_but_leaves_entries_as_saved(monkeypatch, capsys):
    monkeypatch.setenv("OPTPLAT_API_TOKEN", "x" * 24)
    monkeypatch.setenv("OPTPLAT_AUTOSTART_LOOP", "1")
    _stub_server(monkeypatch)
    started = []
    monkeypatch.setattr(entry.Runner, "start", lambda self: started.append(1))
    entry.main()
    out = capsys.readouterr().out
    assert started == [1]
    assert "Automatic entries: off" in out  # the default is still off; autostart does not change it


def test_open_when_ready_waits_for_the_server_then_opens_once(monkeypatch):
    import socket

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    opened = []
    monkeypatch.setattr(entry.webbrowser, "open", lambda url: opened.append(url))
    try:
        entry._open_when_ready("http://127.0.0.1/x", port, timeout_s=3)
    finally:
        server.close()
    assert opened == ["http://127.0.0.1/x"]


def test_open_when_ready_gives_up_quietly_if_the_server_never_starts(monkeypatch):
    import socket

    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()  # nothing listens here now
    opened = []
    monkeypatch.setattr(entry.webbrowser, "open", lambda url: opened.append(url))
    entry._open_when_ready("http://x", port, timeout_s=0.6)
    assert opened == []
