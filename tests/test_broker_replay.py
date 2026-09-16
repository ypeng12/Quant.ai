import unittest
from backend.app.dashboard.broker_replay import build_broker_payload

class BrokerReplayTests(unittest.TestCase):
    def payload(self, events, qty='0', previous=None):
        snapshot=dict(events=events,positions=[dict(symbol='SNDK',qty=qty)],history_complete=True,is_paper=True,observed_at='2026-09-16T16:00:00-04:00')
        return build_broker_payload('SNDK','2026-09-15',snapshot,dict(bars=[],previous_close=previous),now='2026-09-16T16:00:00-04:00')
    def event(self, id, side, qty, price, time='2026-09-15T10:00:00-04:00'):
        return dict(id=id,symbol='SNDK',side=side,qty=str(qty),price=str(price),transaction_time=time)
    def test_duplicate_and_actual_prices_no_assumed_fees(self):
        a=self.event('a','buy',10,100);b=self.event('b','sell',10,103,'2026-09-15T20:00:09-04:00')
        p=self.payload([a,a,b]);self.assertEqual(p['summary']['net_pnl'],30);self.assertEqual(len(p['fills']),2)
        self.assertIsNone(p['summary']['cost']);self.assertGreater(p['chart_end'],630)
    def test_reversal_splits_without_duplicating_quantity(self):
        p=self.payload([self.event('a','sell',5,100),self.event('b','buy',8,90,'2026-09-15T10:05:00-04:00')],qty='3')
        self.assertEqual([x['action'] for x in p['fills']],['X','C','B'])
        self.assertEqual([x['shares'] for x in p['fills']],[5,5,3]);self.assertEqual(p['summary']['realized_fifo_pnl'],50)
    def test_unknown_inventory_never_invents_short_or_pnl(self):
        p=self.payload([self.event('a','sell',5,100)],qty='0')
        self.assertEqual(p['fills'][0]['action'],'SELL');self.assertIsNone(p['summary']['net_pnl']);self.assertIsNone(p['opening_shares'])
    def test_overnight_day_pnl_differs_from_fifo(self):
        rows=[self.event('a','buy',10,90,'2026-09-14T10:00:00-04:00'),self.event('b','sell',10,105)]
        p=self.payload(rows,previous=100)
        self.assertEqual(p['summary']['net_pnl'],50);self.assertEqual(p['summary']['realized_fifo_pnl'],150)
        self.assertIsNone(self.payload(rows)['summary']['net_pnl'])

if __name__=='__main__': unittest.main()
