import gzip
import json
import sqlite3
from pathlib import Path

from optplat import export as ex
from optplat.store import Store

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return [json.loads(line) for line in gzip.open(path, "rt").read().splitlines()]


def make_db(tmp_path):
    db = tmp_path / "t.db"
    s = Store(str(db))
    s.set_state("challenge:attempt", json.dumps({"n": 1, "api_token": "abc"}))
    s.set_state("lane_mark:x", "{}")
    s.set_state("kill_switch", "1")  # not on the allow-list
    s.set_state("config_blob", "private")
    s._db.execute("INSERT INTO equity (ts, equity, cash, open_premium, fictional) VALUES ('2026-11-16T00:00:00', 1000, 900, 100, 0)")
    s._db.execute("INSERT INTO snapshots (symbol, recorded_at, as_of, source, fictional, timestamp_verified, payload) VALUES ('A','t','t','s',0,0,'{}')")
    s._db.execute("INSERT INTO decisions (ts, symbol, kind, disposition, contract, strategy, ref_price, order_id, fictional, payload)"
                  " VALUES ('t','A','ENTRY','FILLED','c','s',1.0,NULL,0,'{\"why\":\"x\",\"account_id\":\"U123\",\"nested\":{\"password\":\"p\"}}')")
    s._db.commit()
    return db


def test_export_writes_only_allow_listed_data_and_redacts_secrets(tmp_path):
    db, out = make_db(tmp_path), tmp_path / "out"
    m = ex.export(str(db), str(out))
    assert m["tables"]["equity"]["rows"] == 1
    assert not (out / "snapshots.jsonl.gz").exists() and "snapshots" in " ".join(m["left_out"])
    state = {r["k"] for r in read(out / "state.jsonl.gz")}
    assert state == {"challenge:attempt", "lane_mark:x"}
    dec = read(out / "decisions.jsonl.gz")[0]["payload"]
    assert dec["why"] == "x" and dec["account_id"] == ex.REDACTED and dec["nested"]["password"] == ex.REDACTED
    text = "".join(gzip.open(p, "rt").read() for p in out.glob("*.gz")) + (out / "manifest.json").read_text()
    assert "abc" not in text and "U123" not in text and "SIMULATED PAPER DATA" in text


def test_export_never_modifies_the_database_and_is_reproducible(tmp_path):
    db = make_db(tmp_path)
    before = db.read_bytes()
    a, b = tmp_path / "a", tmp_path / "b"
    ex.export(str(db), str(a))
    ex.export(str(db), str(b))
    assert db.read_bytes() == before
    assert (a / "equity.jsonl.gz").read_bytes() == (b / "equity.jsonl.gz").read_bytes()


def test_missing_database_fails_without_creating_one(tmp_path):
    assert ex.main(["--db", str(tmp_path / "nope.db"), "--out", str(tmp_path / "o")]) == 1
    assert not (tmp_path / "nope.db").exists()


def test_the_push_script_refuses_anything_not_confirmed_private():
    text = (ROOT / "deploy" / "export_push.sh").read_text()
    assert "isPrivate" in text and "!= \"true\"" in text and "--force" not in text
    assert "OPTPLAT_EXPORT_REPO" in text
