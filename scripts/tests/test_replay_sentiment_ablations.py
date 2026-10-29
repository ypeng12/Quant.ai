import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

PATH=Path(__file__).resolve().parents[1]/'replay_sentiment_ablations.py'
SPEC=importlib.util.spec_from_file_location('text_ablations',PATH)
mod=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(mod)
NAMES=sorted(mod.METADATA_FEATURES|mod.SEMANTIC_FEATURES)


def calibration():
    weights=[.0001 if n=='news_stance_balance' else -.0002 if n=='news_log_count' else 0.0 for n in NAMES]
    return {'status':'fitted_development_only','target_horizon_minutes':30,'mode':'strict_received',
        'training_cutoff':'2026-10-23T00:00:00-04:00','feature_names':NAMES,'means':[0]*12,
        'scales':[1]*12,'weights':weights,'intercept':-.0003}


def row(at='2026-10-23T09:35:00-04:00'):
    values=[1 if n in ('news_stance_balance','news_log_count') else 0 for n in NAMES]
    return {'date':pd.Timestamp(at).date().isoformat(),'decision_at':at,'symbol':'NVDA',
        'C_mu':0.0,'text_adjustment_full_30m':-.0004,'has_text':True,'text_fallback':None,
        'feature_vector':values,'event_ids':['same-source-event'],'evidence_ids':['version1']}


class AblationTests(unittest.TestCase):
    def test_numeric_decomposition_and_eligibility(self):
        r=row();values,eligible=mod.decomposition(r,calibration())
        self.assertTrue(eligible);self.assertAlmostEqual(values['B_full'],-.0004)
        self.assertAlmostEqual(values['metadata_only'],-.0005)
        self.assertAlmostEqual(values['constant_intercept'],-.0003)
        r.update(has_text=False,text_fallback='no_asof_text',text_adjustment_full_30m=0)
        values,eligible=mod.decomposition(r,{'status':'unavailable'})
        self.assertFalse(eligible);self.assertEqual(set(values.values()),{0})
        r['text_adjustment_full_30m']=-.0004
        with self.assertRaises(ValueError):mod.decomposition(r,calibration())

    def test_timestamp_normalization_and_duplicate_rejection(self):
        r=row();r['date']=pd.Timestamp(r['date']);r['decision_at']=pd.Timestamp(r['decision_at'])
        d=mod.normalize_decisions(pd.DataFrame([r]),['2026-10-23'])
        self.assertIn(('2026-10-23','2026-10-23T09:35:00-04:00','NVDA'),d)
        with self.assertRaises(ValueError):mod.normalize_decisions(pd.DataFrame([r,r]),['2026-10-23'])
        r['decision_at']='2026-10-23T09:35:00'
        with self.assertRaises(ValueError):mod.normalize_decisions(pd.DataFrame([r]),['2026-10-23'])

    def test_same_event_cannot_refresh_but_new_event_can(self):
        expiry=mod.EventExpiry()
        self.assertEqual(expiry.step(row(),True)[0],-.0004)
        r=row('2026-10-23T09:55:00-04:00');r['evidence_ids']=['updated-content-version']
        self.assertFalse(expiry.step(r,True)[1])
        value,force,reason=expiry.step(row('2026-10-23T10:05:00-04:00'),True)
        self.assertEqual(value,0);self.assertTrue(force)
        self.assertEqual(expiry.step(row('2026-10-23T10:10:00-04:00'),True)[:2],(0,False))
        r=row('2026-10-23T10:15:00-04:00');r['event_ids']=['genuinely-new-source-id']
        self.assertEqual(expiry.step(r,True)[0],-.0004)
        self.assertEqual(expiry.step(row('2026-10-26T09:35:00-04:00'),True)[:2],(0,False))

    def test_frozen_comparison_exposes_execution_difference(self):
        daily=[{'date':'2026-10-23','net_pnl':1.0,'costs':.2}]
        fills=[{'date':'2026-10-23','fill_time':'2026-10-23T09:35:00-04:00','symbol':'NVDA',
                'quantity':1,'shares_after':1,'reason':'policy_rebalance','reference_price':100,
                'fill_price':100.02,'cost':.02,'notional':100}]
        summary={'net_pnl':1.,'costs':.2}
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'summary.json').write_text(json.dumps(summary))
            pd.DataFrame(daily).to_csv(p/'daily.csv.gz',index=False,compression='gzip')
            pd.DataFrame(fills).to_csv(p/'fills.csv.gz',index=False,compression='gzip')
            self.assertTrue(mod.comparison_to_frozen(daily,fills,summary,p)['exact_fill_identity'])
            changed=copy.deepcopy(fills);changed[0]['quantity']=2
            result=mod.comparison_to_frozen(daily,changed,summary,p)
            self.assertEqual(result['status'],'reproduction_difference')

    def test_one_synthetic_session_all_arms_share_one_covariance_fit(self):
        day='2026-10-23';idx=pd.date_range(day+' 09:30',periods=78,freq='5min',tz='America/New_York')
        frame=pd.DataFrame({'Open':100.,'High':100.1,'Low':99.9,'Close':100.,'Volume':1000.},index=idx)
        frames={s:frame.copy() for s in mod.INPUTS};rows=[]
        for i in range(76):
            for s in mod.TRADED:
                r=row((idx[i]+pd.Timedelta(minutes=5)).isoformat());r['symbol']=s;rows.append(r)
        class FakeCandidate:
            audit={'synthetic':True}
            def weights(self,stamp,current,mu,shortable,text_adjustment):
                return {s:100*(mu[s]+(text_adjustment.returns[s] if text_adjustment else 0)) for s in mod.TRADED}
        with tempfile.TemporaryDirectory() as tmp,patch.object(mod.PriceCandidate,'fit',return_value=FakeCandidate()) as fit:
            result=mod.run_ablations(frames,pd.DataFrame(rows),[{'date':day,'price':{},'text':calibration()}],
                                    [day],Path(tmp)/'new')
            self.assertEqual(fit.call_count,1)
            self.assertEqual(len(result['results']),10)
            self.assertEqual(result['results']['2bps_C']['fill_count'],0)
            self.assertEqual(result['expiry_actions']['expired_force_flat_once'],3)
            self.assertEqual(result['adjustment_counts']['B_expiring'],18)
            self.assertFalse(result['promoted'])


if __name__=='__main__':unittest.main()
