import importlib.util
from datetime import datetime,timedelta
from pathlib import Path
import tempfile
import unittest

MODULE=Path(__file__).resolve().parents[1]/'diagnose_sentiment_increment.py'
spec=importlib.util.spec_from_file_location('sentiment_increment_diagnostic',MODULE)
diag=importlib.util.module_from_spec(spec);spec.loader.exec_module(diag)


def mark(at,phase,price,shares):
    return {'date':at.date().isoformat(),'timestamp':at.isoformat(),'phase':phase,
            'X_price':str(price),'X_shares':str(shares)}


class DiagnosticTests(unittest.TestCase):
    def test_inventory_exact_gap_and_intrabar_attribution(self):
        at=datetime.fromisoformat('2026-10-23T09:30:00-04:00')
        b=[mark(at,'open_before_orders',100,0),mark(at+timedelta(minutes=5),'bar_close',101,-2),
           mark(at+timedelta(minutes=5),'open_before_orders',102,-2),mark(at+timedelta(minutes=10),'bar_close',103,0)]
        c=[{**r,'X_shares':'0'} for r in b]
        rows=diag.inventory_attribution(b,c,['X'],{})
        self.assertEqual(sum(r['intrabar_gross_pnl_difference'] for r in rows),-2)
        self.assertEqual(sum(r['gap_gross_pnl_difference'] for r in rows),-2)
        self.assertEqual(sum(r['gross_pnl_difference'] for r in rows),-4)
        with self.assertRaises(ValueError):diag.inventory_attribution(b,c[:-1],['X'],{})
        c[0]['X_price']='99'
        with self.assertRaises(ValueError):diag.inventory_attribution(b,c,['X'],{})

    def test_complete_same_horizon_endpoints_required(self):
        at=datetime.fromisoformat('2026-10-23T09:35:00-04:00')
        opens={at+timedelta(minutes=i*5):{'X_price':100+i} for i in range(6)}
        closes={at+timedelta(minutes=(i+1)*5):{'X_price':101+i} for i in range(6)}
        self.assertAlmostEqual(diag.reference_path(opens,closes,at.isoformat(),30,'X'),600)
        del opens[at+timedelta(minutes=10)]
        self.assertIsNone(diag.reference_path(opens,closes,at.isoformat(),30,'X'))
        with self.assertRaises(ValueError):diag.reference_path(opens,closes,at.isoformat(),0,'X')

    def test_forecast_residual_direction_clip_and_error(self):
        at=datetime.fromisoformat('2026-10-23T09:35:00-04:00')
        marks=[]
        for i in range(6):
            marks.extend([mark(at+timedelta(minutes=5*i),'open_before_orders',100+i,0),
                          mark(at+timedelta(minutes=5*(i+1)),'bar_close',101+i,0)])
        names=['news_scored_fraction','futu_scored_fraction','news_stance_balance','futu_stance_balance']
        d={'date':'2026-10-23','symbol':'X','decision_at':at.isoformat(),'text_adjustment_full_30m':-.0005,
           'C_mu':0,'C_scale':0,'text_fallback':None,'feature_vector':[0]*4,
           'evidence':[{'published_at':'2026-10-22T12:00:00-04:00','received_at':'2026-10-22T13:00:00-04:00'}]}
        cal={'training_cutoff':'2026-10-23T00:00:00-04:00','feature_names':names,'intercept':-.0006,
             'means':[0]*4,'scales':[1]*4,'weights':[0]*4}
        rows,contrib=diag.forecast_diagnostics([d],{'2026-10-23':{'text':cal}},marks)
        self.assertEqual(len(contrib),4)
        self.assertAlmostEqual(rows[0]['realized_return_bps'],600)
        self.assertEqual(rows[0]['absolute_error_B_minus_C_bps'],5)
        self.assertTrue(rows[0]['clip_saturated'])
        self.assertFalse(rows[0]['revision_same_direction_as_residual'])
        cal['training_cutoff']=at.isoformat()
        with self.assertRaises(ValueError):diag.forecast_diagnostics([d],{'2026-10-23':{'text':cal}},marks)

    def test_overlapping_labels_not_counted_as_independent(self):
        at=datetime.fromisoformat('2026-10-23T09:35:00-04:00')
        rows=[]
        for offset in [0,5,30]:
            start=at+timedelta(minutes=offset)
            rows.append({'symbol':'X','decision_at':start.isoformat(),
                'realized_end_at':(start+timedelta(minutes=30)).isoformat(),
                'realized_return_bps':1,'revision_same_direction_as_return':False,
                'revision_same_direction_as_residual':False,'absolute_error_B_minus_C_bps':5,
                'squared_error_B_minus_C_bps2':35})
        result=diag.describe_forecasts(rows)
        self.assertEqual(result['rows'],3);self.assertEqual(result['nonoverlapping_rows'],2)
        self.assertEqual(result['same_direction_as_return'],0)
        self.assertIn('dependent',result['independence_warning'])

    def test_frozen_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):diag.diagnose(Path(temp)/'frozen',temp,temp)


if __name__=='__main__':unittest.main()
