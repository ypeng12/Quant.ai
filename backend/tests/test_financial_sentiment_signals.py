"""Standalone public API checks; never import main_api or trading services."""
import copy
import gzip
import importlib.util
import json
from pathlib import Path
import tempfile
import os
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

MODULE_PATH = Path(__file__).resolve().parents[1] / "app/financial_sentiment_signals.py"
spec = importlib.util.spec_from_file_location("financial_sentiment_signals_standalone", MODULE_PATH)
signals = importlib.util.module_from_spec(spec)
spec.loader.exec_module(signals)


def fixture():
    evidence = {"news:1:hash": dict(source="news", source_id="1", title="Company updates its outlook",
                published_at="2026-10-23T15:30:00-04:00", updated_at="2026-10-23T15:30:00-04:00",
                received_at="2026-10-23T15:40:00-04:00", available_at="2026-10-23T15:41:00-04:00", receipt_verified=True)}
    points = []
    for i, (start, end) in enumerate((('15:45', '15:50'), ('15:50', '15:55'), ('15:55', '16:00'))):
        point = dict(timestamp=f"2026-10-23T{end}:00-04:00", bar_start=f"2026-10-23T{start}:00-04:00",
                     price=dict(open=100+i, high=102+i, low=99+i, close=101+i, volume=1000), has_decision=i == 0, text=None)
        for name in ('A', 'C', 'B'):
            point[name] = dict(forecast_bps=(2 + (5/6 if name == 'B' else 0)) if i == 0 else None,
                               nominal_horizon_minutes=5 if name == 'A' else 30,
                               effective_horizon_minutes=5 if i == 0 else None, shares=0, weight=0,
                               realized_bps=(102/101-1)*10000 if i == 0 else None,
                               realized_end_at="2026-10-23T15:55:00-04:00" if i == 0 else None)
        if i == 0:
            point['text'] = dict(has_text=True, primary_asof_eligible=True,
                full_adjustment_bps=5, effective_adjustment_bps=5/6,
                raw_adjustment_bps=7, intercept_bps=1, clip_adjustment_bps=-2,
                rounding_adjustment_bps=0, fallback_reason=None, feature_values={'f':2},
                contributions=[dict(feature='f', value=2, standardized=2, coefficient_bps=3, contribution_bps=6)],
                evidence_keys=['news:1:hash'])
        points.append(point)
    return dict(schema_version=1, generated_at="2026-10-28T16:00:00Z", evaluation_kind="retrospective_development",
                cost_bps_per_side=2, symbols=['NVDA'], dates=['2026-10-23'], default_selection=dict(symbol='NVDA',date='2026-10-23'),
                tracks=[dict(id='B',label='Text candidate',status='fitted_development_only',as_of='2026-10-23',detail='Saved development calibration.')],
                feature_definitions=[dict(id='f',label='Feature',unit='count',detail='A retained structural feature.')],
                summary=dict(series_count=1,decision_count=1,changed_prediction_count=1,distinct_receipt_dates=['2026-10-23']),
                evidence=evidence,series=[dict(symbol='NVDA',date='2026-10-23',C_scale=.5,
                    text_calibration=dict(status='fitted_development_only',reason=None,training_text_rows=120,training_sessions=5,training_cutoff='2026-10-23T00:00:00-04:00'),
                    points=points,fills=[])],limitations=['Retrospective diagnostics, not causal attribution.'])


class SignalSchemaTests(unittest.TestCase):
    def test_valid_horizon_and_contribution_reconciliation(self):
        data = signals.validate_public_signals(fixture())
        self.assertEqual(data['summary']['decision_count'],1)
        p=data['series'][0]['points'][0]
        self.assertAlmostEqual(p['B']['forecast_bps']-p['C']['forecast_bps'],5/6)

    def test_recursive_allowlist_drops_private_fields(self):
        data=fixture()
        data['account_id']='private'
        data['evidence']['news:1:hash']['body']='private article body'
        data['evidence']['news:1:hash']['provenance']={'path':'/Users/private/source.json'}
        data['series'][0]['points'][0]['B']['account_equity']=1234
        result=json.dumps(signals.validate_public_signals(data))
        for word in ('account_id','article body','/Users/','account_equity','provenance'):
            self.assertNotIn(word,result)

    def test_local_path_in_public_title_rejected(self):
        data=fixture();data['evidence']['news:1:hash']['title']='/Users/owner/private.json'
        with self.assertRaises(ValueError):signals.validate_public_signals(data)

    def test_late_receipt_cannot_be_used_early(self):
        data=fixture();data['evidence']['news:1:hash']['received_at']='2026-10-23T15:49:30-04:00'
        data['evidence']['news:1:hash']['available_at']='2026-10-23T15:50:30-04:00'
        with self.assertRaises(ValueError):signals.validate_public_signals(data)

    def test_processing_delay_not_forged(self):
        data=fixture();data['evidence']['news:1:hash']['available_at']='2026-10-23T15:40:01-04:00'
        with self.assertRaises(ValueError):signals.validate_public_signals(data)

    def test_unknown_is_not_false_zero_outcome(self):
        data=fixture();point=data['series'][0]['points'][1]
        point['A']['realized_bps']=0
        with self.assertRaises(ValueError):signals.validate_public_signals(data)

    def test_wrong_horizon_rejected(self):
        data=fixture();data['series'][0]['points'][0]['C']['effective_horizon_minutes']=30
        with self.assertRaises(ValueError):signals.validate_public_signals(data)

    def test_wrong_forward_return_rejected_against_prices(self):
        data=fixture();data['series'][0]['points'][0]['A']['realized_bps']+=10
        with self.assertRaises(ValueError):signals.validate_public_signals(data)

    def test_contribution_and_clip_tampering_rejected(self):
        for field in ('raw_adjustment_bps','clip_adjustment_bps','effective_adjustment_bps'):
            data=fixture();data['series'][0]['points'][0]['text'][field]+=1
            with self.assertRaises(ValueError):signals.validate_public_signals(data)

    def test_future_training_rejected(self):
        data=fixture();data['series'][0]['text_calibration']['training_cutoff']='2026-10-24T00:00:00-04:00'
        with self.assertRaises(ValueError):signals.validate_public_signals(data)

    def test_duplicate_series_or_false_summary_rejected(self):
        data=fixture();data['series'].append(copy.deepcopy(data['series'][0]))
        with self.assertRaises(ValueError):signals.validate_public_signals(data)
        data=fixture();data['summary']['changed_prediction_count']=0
        with self.assertRaises(ValueError):signals.validate_public_signals(data)

    def test_nonfinite_and_false_fill_rejected(self):
        data=fixture();data['series'][0]['points'][0]['price']['close']=float('nan')
        with self.assertRaises(ValueError):signals.validate_public_signals(data)
        data=fixture();data['series'][0]['fills']=[dict(model='B',timestamp='2026-10-23T15:50:00-04:00',side='buy',quantity=-1,fill_price=100,reason='policy_rebalance')]
        with self.assertRaises(ValueError):signals.validate_public_signals(data)

    def test_read_only_route_and_missing_invalid_snapshots(self):
        app=FastAPI();app.include_router(signals.router)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'snapshot.json'
            with patch.object(signals,'PUBLIC_SIGNALS_PATH',path):
                client=TestClient(app)
                self.assertEqual(client.get('/api/research/financial-sentiment/signals').status_code,404)
                path.write_text('{invalid')
                self.assertEqual(client.get('/api/research/financial-sentiment/signals').status_code,503)
                path.write_text(json.dumps(fixture()))
                self.assertEqual(client.get('/api/research/financial-sentiment/signals').status_code,200)
                self.assertEqual(client.post('/api/research/financial-sentiment/signals').status_code,405)

    def test_cached_response_skips_revalidation_and_json_encoder(self):
        app=FastAPI();app.include_router(signals.router)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'snapshot.json';path.write_text(json.dumps(fixture()))
            with patch.object(signals,'PUBLIC_SIGNALS_PATH',path), patch.object(signals,'_CACHE',None), patch.object(signals,'validate_public_signals',wraps=signals.validate_public_signals) as validate:
                client=TestClient(app)
                first=client.get('/api/research/financial-sentiment/signals',headers={'Accept-Encoding':'gzip'})
                self.assertEqual(first.status_code,200)
                self.assertEqual(first.headers['content-encoding'],'gzip')
                self.assertEqual(first.json()['schema_version'],1)
                second=client.get('/api/research/financial-sentiment/signals',headers={'Accept-Encoding':'identity'})
                self.assertEqual(second.status_code,200)
                self.assertNotIn('content-encoding',second.headers)
                self.assertEqual(first.json(),second.json())
                self.assertEqual(validate.call_count,1)
                unchanged=client.get('/api/research/financial-sentiment/signals',headers={'If-None-Match':first.headers['etag']})
                self.assertEqual(unchanged.status_code,304)
                self.assertEqual(unchanged.content,b'')

    def test_cached_file_tamper_never_serves_previous_valid_data(self):
        app=FastAPI();app.include_router(signals.router)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'snapshot.json';path.write_text(json.dumps(fixture()))
            with patch.object(signals,'PUBLIC_SIGNALS_PATH',path), patch.object(signals,'_CACHE',None):
                client=TestClient(app)
                valid=client.get('/api/research/financial-sentiment/signals')
                before=path.stat()
                # Same byte count and restored mtime: ctime still invalidates.
                raw=path.read_text().replace('"full_adjustment_bps": 5','"full_adjustment_bps": 4')
                path.write_text(raw);os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
                bad=client.get('/api/research/financial-sentiment/signals',headers={'If-None-Match':valid.headers['etag']})
                self.assertEqual(bad.status_code,503)
                path.unlink()
                self.assertEqual(client.get('/api/research/financial-sentiment/signals').status_code,404)

    def test_gzip_quality_zero_is_respected(self):
        self.assertFalse(signals._accepts_gzip('gzip;q=0, br'))
        self.assertFalse(signals._accepts_gzip('*;q=1, gzip;q=0'))
        self.assertTrue(signals._accepts_gzip('br, gzip;q=0.5'))

    def test_gzip_only_deployment_is_validated_and_plain_invalid_does_not_fallback(self):
        app=FastAPI();app.include_router(signals.router)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'snapshot.json'
            sidecar=path.with_suffix('.json.gz')
            sidecar.write_bytes(gzip.compress(json.dumps(fixture()).encode(),mtime=0))
            with patch.object(signals,'PUBLIC_SIGNALS_PATH',path), patch.object(signals,'_CACHE',None):
                client=TestClient(app)
                self.assertEqual(client.get('/api/research/financial-sentiment/signals').status_code,200)
                path.write_text('{invalid')
                self.assertEqual(client.get('/api/research/financial-sentiment/signals').status_code,503)
                path.unlink();sidecar.write_bytes(b'bad gzip')
                self.assertEqual(client.get('/api/research/financial-sentiment/signals').status_code,503)

    def test_gzip_decompression_bound_precedes_json_validation(self):
        app=FastAPI();app.include_router(signals.router)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'snapshot.json';sidecar=path.with_suffix('.json.gz')
            raw=json.dumps(fixture()).encode()+b' '*10000
            compressed=gzip.compress(raw,mtime=0)
            self.assertLess(len(compressed),2000)
            sidecar.write_bytes(compressed)
            with patch.object(signals,'PUBLIC_SIGNALS_PATH',path),patch.object(signals,'_CACHE',None),patch.object(signals,'MAX_PUBLIC_BYTES',2000),patch.object(signals,'validate_public_signals',side_effect=AssertionError('Oversized input must not be parsed')):
                response=TestClient(app).get('/api/research/financial-sentiment/signals')
                self.assertEqual(response.status_code,503)


class IndependentTrainingTrackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = MODULE_PATH.parents[2] / 'scripts/export_quant_signal_explorer.py'
        spec = importlib.util.spec_from_file_location('signal_exporter_standalone', path)
        cls.exporter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.exporter)

    def summary(self):
        return dict(schema_version=1, model='price_label_bert', evaluation_kind='retrospective_development',
                    generated_at='2026-10-28T23:00:00Z', test_start='2023-09-01', horizon_sessions=10,
                    target='company minus SPY split-adjusted price return', promoted=False, alpha_established=False,
                    actual_optimizer_steps=272, planned_optimizer_steps=272, completed_companies=['A','AMZN','MSFT'],
                    status='complete', heldout_predictions_completed=True, heldout_outcomes_opened=True,
                    cases=[{'company':c} for c in ['A','AMZN','MSFT']], training_rows=272, heldout_rows=154)

    def test_real_training_is_separate_from_2026_curves(self):
        track = self.exporter.price_bert_track(self.summary())
        data = fixture(); prior = copy.deepcopy(data['series']); data['tracks'].append(track)
        result = signals.validate_public_signals(data)
        self.assertEqual(result['series'], prior)
        self.assertIn('272/272 real optimizer steps', track['detail'])
        self.assertIn('not an input to these 2026 A/C/B curves', track['detail'])
        self.assertIn('2023', track['label'])

    def test_false_completed_claim_and_live_promotion_are_rejected(self):
        for field,value in [('actual_optimizer_steps',0),('heldout_predictions_completed',False),
                            ('heldout_outcomes_opened',False),('completed_companies',['A']),('promoted',True)]:
            data = self.summary(); data[field] = value
            with self.subTest(field=field),self.assertRaises(ValueError):
                self.exporter.price_bert_track(data)

    def test_incomplete_actual_training_is_not_called_completed(self):
        data = self.summary(); data.update(status='incomplete',actual_optimizer_steps=10,
                                           completed_companies=[],cases=[],heldout_predictions_completed=False,
                                           heldout_outcomes_opened=False)
        track = self.exporter.price_bert_track(data)
        self.assertEqual(track['status'],'Training incomplete')
        self.assertIn('10/272 real optimizer steps',track['detail'])

    def test_completed_training_is_retained_when_evaluation_is_incomplete(self):
        data = self.summary(); data.update(status='incomplete',cases=[],heldout_predictions_completed=False,
                                           heldout_outcomes_opened=False)
        track = self.exporter.price_bert_track(data)
        self.assertEqual(track['status'],'Final-layer training complete; evaluation incomplete')
        self.assertIn('272/272 real optimizer steps',track['detail'])


if __name__=='__main__':unittest.main()
