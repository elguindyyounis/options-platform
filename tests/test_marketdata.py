

def test_yahoo_chain_with_no_tables_is_no_rows_not_a_crash():
    # Seen on the owner's Mac 2026-11-27: "'NoneType' object has no attribute 'to_dict'" when Yahoo answered with nothing.
    from datetime import date
    from types import SimpleNamespace

    from optplat.marketdata import YahooDataProvider

    class Ticker:
        def __init__(self, chain):
            self.chain = chain

        def option_chain(self, _expiry):
            return self.chain

    y = YahooDataProvider()
    assert y._chain_rows(Ticker(None), "QQQ", date(2026, 12, 18)) == []
    assert y._chain_rows(Ticker(SimpleNamespace(calls=None, puts=None)), "QQQ", date(2026, 12, 18)) == []
