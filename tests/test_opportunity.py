import unittest
from optplat.opportunity import assess

class OpportunityTests(unittest.TestCase):
    def result(self, **kw):
        args=dict(spot=100.,strike=100.,right="C",bid=2.9,ask=3.,iv=.3,dte=30,
                  closes=[100*(1.03 if i%2 else 1) for i in range(61)])
        args.update(kw)
        return assess(**args)
    def test_slow_and_flat_are_not_picks(self):
        self.assertFalse(self.result(closes=[100.]*61)['eligible'])
        self.assertFalse(self.result(closes=[100+i*.001 for i in range(61)])['eligible'])
    def test_economical_call_and_put_pass(self):
        for side in ('C','P'):
            r=self.result(right=side)
            self.assertTrue(r['eligible'],r)
            self.assertLess(r['flat_net_return_pct'],0)
            self.assertLess(r['adverse_net_return_pct'],0)
    def test_cost_and_iv_can_disqualify_active_name(self):
        self.assertFalse(self.result(bid=29.,ask=30.,iv=2.)['eligible'])
    def test_missing_and_invalid_evidence_fail_closed(self):
        for kw in [dict(closes=[]),dict(iv=None),dict(iv=float('nan')),dict(bid=0),dict(ask=float('inf')),dict(right='X'),dict(multiplier=0)]:
            self.assertFalse(self.result(**kw)['eligible'])
    def test_far_otm_is_not_promoted_by_cheap_premium(self):
        self.assertFalse(self.result(strike=170.,bid=.09,ask=.1)['eligible'])
    def test_horizon_is_bounded_by_expiry(self):
        r=self.result(dte=2)
        self.assertLess(r['elapsed_calendar_days'],2)
    def test_contract_multiplier_changes_fee_impact(self):
        self.assertLess(self.result(multiplier=1)['favorable_net_return_pct'],self.result()['favorable_net_return_pct'])
    def test_no_symbol_blacklist_or_probability_claim(self):
        r=self.result()
        self.assertIn('not forecasts',r['assumptions'])
        self.assertNotIn('probability',r)

class SelectionIntegrationTests(unittest.TestCase):
    def test_strategy_rejects_flat_move_and_records_economics_for_pass(self):
        from dataclasses import replace
        from test_engine import snapshot
        from helpers import NOW
        from optplat.strategy import LiquidTrendStrategy
        snap=snapshot()
        proposals=LiquidTrendStrategy().propose(snap,NOW)
        self.assertTrue(proposals)
        self.assertTrue(proposals[0].rationale['opportunity']['eligible'])
        slow=replace(snap,closes=tuple(158.94+i*.001 for i in range(60)))
        self.assertFalse(LiquidTrendStrategy().propose(slow,NOW))
        self.assertIn('movement',LiquidTrendStrategy().explain_no_proposal(slow,NOW))
    def test_scanner_never_promotes_missing_history_despite_volume(self):
        from dataclasses import replace
        from test_engine import snapshot
        from helpers import NOW
        from optplat.scanner import unusual_contracts
        snap=snapshot()
        snap=replace(snap,closes=(),rows=(replace(snap.rows[0],volume=20000),))
        rows=unusual_contracts(snap,NOW)
        self.assertTrue(rows)
        self.assertEqual(rows[0]['decision'],'OBSERVE_ONLY')
        self.assertIn('daily closes',rows[0]['why_observe_only'])
