"""Evaluate the baseline strategy over recorded snapshots:  python -m optplat.evaluate --entries

Reads the recorder's database read-only. Everything runs in a throwaway in-memory simulation; the live
settings and the database are never changed.
"""
from __future__ import annotations

import argparse
import sys

from .evaluation import evaluate, format_report
from .risk import RiskPolicy
from .store import Store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="optplat.db", help="database written by the recorder (opened read-only)")
    ap.add_argument("--symbols", default="", help="comma-separated tickers to include (default: all recorded)")
    ap.add_argument("--entries", action="store_true",
                    help="turn automatic entries ON inside this simulation (without it nothing is traded)")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="accept quotes with no exchange timestamp (needed for recorded Yahoo data). Research only")
    ap.add_argument("--fictional", action="store_true", help="evaluate recorded fictional demo data (meaningless)")
    args = ap.parse_args(argv)

    try:
        store = Store(args.db, read_only=True)
        rows = store.list_snapshots(include_fictional=args.fictional, limit=100_000)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not read snapshots from {args.db}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    wanted = {s.strip().upper() for s in args.symbols.split(",") if s.strip()}
    if wanted:
        rows = [r for r in rows if r["symbol"] in wanted]
    if not rows:
        print("No recorded snapshots found. Run the platform during market hours first (the recorder is on by default).")
        return 1
    if len(rows) >= 100_000:
        print("Warning: only the oldest 100000 snapshots were loaded.", file=sys.stderr)
    if args.allow_unverified:
        print("WARNING: quotes without verified timestamps are accepted in this replay. Research only.")
    if not args.entries:
        print("NOTE: automatic entries are off in this replay, so no trades will be made. Re-run with --entries.")
    policy = RiskPolicy(require_verified_quote_time=not args.allow_unverified)
    try:
        result = evaluate(rows, config={"auto_entries": args.entries}, policy=policy)
    except ValueError as exc:
        print(f"Cannot evaluate: {exc}")
        return 1
    print(format_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
