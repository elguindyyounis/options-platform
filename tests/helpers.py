from datetime import date, datetime, timezone

from optplat.models import OptionContract, OrderIntent, Quote, Right

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=timezone.utc)
CONTRACT = OptionContract("SPY", date(2026, 12, 18), Right.CALL, 600.0)


def make_quote(bid=1.90, ask=2.00, *, contract=CONTRACT, as_of=NOW, verified=True):
    return Quote(contract, bid, ask, as_of, "test", timestamp_verified=verified)


def make_intent(key="key-00000001", *, qty=4, limit=2.02, contract=CONTRACT):
    return OrderIntent(key, "cand-1", contract, qty, limit)
