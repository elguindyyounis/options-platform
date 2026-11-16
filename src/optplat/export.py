"""Nightly, secret-free export of the paper database, so the research agents can see real results.

Read-only: the database is opened with ``mode=ro``. Only an allow-list of tables and state keys is exported, as
gzipped JSON lines with a manifest. Raw market snapshots are left out (large, and not needed to judge results).
Any field whose name looks like a credential or an account is redacted. Everything exported is simulated paper
data and is labelled so; it is never real money. The push step (``deploy/export_push.sh``) refuses to run unless
the destination repository is confirmed private.

    python -m optplat.export --db optplat.db --out export/
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

TABLES = ("orders", "audit", "decisions", "equity", "lane_trades", "unusual_history", "tracker_marks", "shadow_follows", "shadow_points", "agent_weights",
          "scan_results", "hypotheses", "hypothesis_results", "data_issues")
STATE_PREFIXES = ("challenge:", "lane_mark:", "optlane_last_result:", "optlane_last_run:")
_SECRET_KEY = re.compile(r"token|secret|password|passwd|api[_-]?key|authorization|account|credential", re.I)
REDACTED = "[redacted]"


def redact(value: Any) -> Any:
    """Recursively replace the value of any key that looks like a credential or an account id."""
    if isinstance(value, dict):
        return {k: (REDACTED if _SECRET_KEY.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, str) and value[:1] in "{[":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return redact({k: _decode(row[k]) for k in row.keys()})


def _write(path: Path, rows: list[dict[str, Any]]) -> str:
    data = "".join(json.dumps(r, sort_keys=True, default=str) + "\n" for r in rows).encode()
    with open(path, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:  # mtime 0: same data, same bytes
        gz.write(data)
    return hashlib.sha256(data).hexdigest()


def export(db_path: str, out_dir: str, *, now: Optional[datetime] = None, build_id: str = "unknown") -> dict[str, Any]:
    """Write the allow-listed tables under ``out_dir`` and return the manifest (also written as manifest.json)."""
    src = Path(db_path)
    if not src.is_file():
        raise FileNotFoundError("database not found")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    have = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    tables: dict[str, Any] = {}
    try:
        for name in TABLES:
            if name not in have:
                tables[name] = {"rows": 0, "missing": True}
                continue
            rows = [_row(r) for r in conn.execute(f"SELECT * FROM {name}")]  # noqa: S608 - fixed allow-list
            tables[name] = {"rows": len(rows), "sha256": _write(out / f"{name}.jsonl.gz", rows)}
        if "state" in have:
            rows = [_row(r) for r in conn.execute("SELECT k, v FROM state ORDER BY k")
                    if str(r["k"]).startswith(STATE_PREFIXES)]
            tables["state"] = {"rows": len(rows), "sha256": _write(out / "state.jsonl.gz", rows)}
    finally:
        conn.close()
    manifest = {
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "build_id": build_id,
        "label": "SIMULATED PAPER DATA. Not real money, not proof of an edge. Secrets and account ids are redacted.",
        "tables": tables,
        "left_out": ["snapshots", "market_snapshots", "market_quotes", "state keys outside the allow-list"],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main(argv: Optional[list[str]] = None) -> int:
    from .deploy import build_id

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", default="optplat.db")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    try:
        m = export(args.db, args.out, build_id=build_id())
    except (OSError, sqlite3.Error) as exc:
        print(f"export failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print("exported " + ", ".join(f"{k}={v['rows']}" for k, v in m["tables"].items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
