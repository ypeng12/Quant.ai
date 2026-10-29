"""Small offline tests for evidence dependence and diagnostic arithmetic."""
import copy
import importlib.util
from pathlib import Path
import unittest

path=Path(__file__).resolve().parents[1]/'audit_sentiment_feature_quality.py'
spec=importlib.util.spec_from_file_location('sentiment_feature_diagnostics',path)
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)


def row(day='2026-10-22',clock='09:35',symbol='NVDA'):
    return dict(date=day,decision_at=f'{day}T{clock}:00-04:00',symbol=symbol,has_text=True,
                feature_vector=[0.0]*12,text_adjustment_full_30m=-.0005,
                evidence=[dict(source='news',source_id='one',content_hash='hash',
                               received_at='2026-10-21T17:12:24+00:00',
                               provenance={'response_file':'/retained/one-response.json'})])


class FeatureQualityTests(unittest.TestCase):
    def test_tags_do_not_become_direct_company_relevance(self):
        obs=dict(title='Meta earnings preview',text='Broad AI market context',symbols=['META','NVDA'])
        result=audit.association('NVDA',obs)
        self.assertFalse(result['target_mentioned_in_title'])
        self.assertEqual(result['source_symbol_count'],2)
        self.assertFalse(result['semantic_relevance_verified'])

    def test_chinese_and_ticker_literal_mentions_are_only_proxies(self):
        obs=dict(title='公司更新',text='$閃迪 (SNDK.US)$ 買入嗎',symbols=['SNDK'])
        result=audit.association('SNDK',obs)
        self.assertFalse(result['target_mentioned_in_title'])
        self.assertTrue(result['target_mentioned_in_title_or_excerpt'])
        self.assertFalse(result['semantic_relevance_verified'])

    def test_reused_receipts_do_not_turn_into_independent_batches(self):
        rows=[row(clock='09:35'),row(clock='09:40'),row(day='2026-10-23'),row(symbol='TSLA')]
        result=audit.dependence(rows)
        self.assertEqual(result['retained_response_batches'],1)
        self.assertEqual(result['unique_document_versions'],1)
        self.assertEqual(result['unique_company_document_associations'],2)
        self.assertEqual(result['consecutive_pairs_same_evidence_set'],1)
        self.assertIsNone(result['independent_semantic_events'])

    def test_training_only_mature_full_horizon_rows(self):
        rows=[row(clock='15:25'),row(clock='15:30'),row(day='2026-10-23')]
        retained=audit.training_rows(rows,'2026-10-23T00:00:00-04:00')
        self.assertEqual(len(retained),1)
        self.assertEqual(retained[0]['decision_at'],'2026-10-22T15:25:00-04:00')
        self.assertEqual(audit.training_rows([row()],'2026-10-22T10:05:00-04:00'),[])

    def test_centered_zero_feature_is_not_a_zero_contribution(self):
        r=row();r['text_adjustment_full_30m']=-.0001
        c=dict(means=[1]+[0]*11,scales=[1]*12,weights=[.0001]+[0]*11,intercept=0)
        result=audit.contributions(r,c)
        self.assertEqual(result['raw_bps'],-1)
        self.assertEqual(result['features_bps']['news_log_count'],-1)
        self.assertEqual(r['feature_vector'][0],0)

    def test_clipping_reconciles_and_tampered_delta_is_rejected(self):
        c=dict(means=[0]*12,scales=[1]*12,weights=[0]*12,intercept=-.003)
        result=audit.contributions(row(),c)
        self.assertEqual(result['raw_bps'],-30)
        self.assertEqual(result['clip_bps'],25)
        self.assertEqual(result['saved_bps'],-5)
        bad=row();bad['text_adjustment_full_30m']=.0005
        with self.assertRaises(ValueError):audit.contributions(bad,c)

    def test_nonoverlap_is_per_company_not_independent_information(self):
        rows=[row(clock='09:35'),row(clock='09:40'),row(clock='10:05'),row(symbol='TSLA')]
        self.assertEqual(audit.nonoverlap_count(rows),3)
        self.assertEqual(audit.dependence(rows)['retained_response_batches'],1)


if __name__=='__main__':unittest.main()
