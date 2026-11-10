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
