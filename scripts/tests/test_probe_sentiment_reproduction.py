import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

P=Path(__file__).resolve().parents[1]/'probe_sentiment_reproduction.py'
S=importlib.util.spec_from_file_location('reproduction_probe',P)
m=importlib.util.module_from_spec(S);S.loader.exec_module(m)


class ProbeTests(unittest.TestCase):
    def test_same_clock_fills_are_excluded_from_decision_state(self):
        fills=[{'fill_time':'2026-09-14T09:35:00-04:00','symbol':'NVDA','quantity':-2,
            'fill_price':100.,'commission_cost':0.,'cash_after':50200.,'shares_after':-2},
            {'fill_time':'2026-09-14T10:00:00-04:00','symbol':'NVDA','quantity':1,
            'fill_price':101.,'commission_cost':0.,'cash_after':50099.,'shares_after':-1}]
        state=m.reconstruct_state(fills,m.DECISION,dict.fromkeys(m.SYMBOLS,101.))
        self.assertEqual(state['shares']['NVDA'],-2)
        self.assertEqual(state['cash'],50200.)
        self.assertEqual(state['equity'],49998.)
        self.assertEqual(state['frozen_next_open_shares_after_orders']['NVDA'],-1)
        self.assertEqual(len(state['prior_fills']),1)

    def test_cash_reconciliation_and_aware_clocks(self):
        fill={'fill_time':'2026-09-14T09:35:00-04:00','symbol':'NVDA','quantity':-2,
              'fill_price':100.,'commission_cost':0.,'cash_after':999.,'shares_after':-2}
        with self.assertRaises(ValueError):m.reconstruct_state([fill],m.DECISION,dict.fromkeys(m.SYMBOLS,100.))
        with self.assertRaises(ValueError):m.reconstruct_state([],'2026-09-14T10:00:00',dict.fromkeys(m.SYMBOLS,100.))

    def test_probe_reports_multi_ulp_integer_underflow_without_fixing_it(self):
        # Deliberate tiny solver residue, not an assertion about the actual run.
        current=-22*100/50000
        target=np.nextafter(np.nextafter(np.nextafter(current,0),0),0)
        state={'equity':50000.,'shares':{'NVDA':-22,'SNDK':0,'TSLA':0},
               'close_prices':dict.fromkeys(m.SYMBOLS,100.),
               'current_weights':{'NVDA':current,'SNDK':0.,'TSLA':0.}}
        with patch.object(m,'target_weights',return_value={'NVDA':float(target),'SNDK':0.,'TSLA':0.}):
            result=m.qp_probe(dict.fromkeys(m.SYMBOLS,0.),np.eye(3)*1e-8,state,'slsqp')
        x=result['symbols']['NVDA']
        self.assertLess(x['distance_to_nearest_integer_shares'],1e-12)
        self.assertEqual(x['integer_target'],-21)
        self.assertGreater(x['no_trade_margin_bps'],0)
        self.assertLess(x['absolute_raw_minus_absolute_current_in_ulps'],-1)


if __name__=='__main__':unittest.main()
