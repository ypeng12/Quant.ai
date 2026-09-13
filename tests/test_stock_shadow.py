"""Synthetic paper decision integration; no broker or real future observation."""
import importlib.util,json,sys
from pathlib import Path
from dataclasses import asdict
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT/'backend/tests'))
from test_stock_policy import panel,STOCKS as FOUR
from test_liquid_policy import metadata,LiquidityRules
spec=importlib.util.spec_from_file_location('stock_shadow',ROOT/'scripts/shadow_stock_policy.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_paper_adapter_records_per_stock_selection_without_assuming_fills(tmp_path,monkeypatch):
    frames=panel();bars=tmp_path/'bars';bars.mkdir()
    for s,f in frames.items():f.to_parquet(bars/f'{s}.parquet')
    manifest=dict(registered_at='2026-08-30T21:00Z',specification=dict(candidate='noncrypto_stock_selector',input_symbols=list(frames),
        max_data_age_seconds=300,cost_bps=5,liquidity_rules=asdict(LiquidityRules(min_adv=1))))
    monkeypatch.setattr(module,'read_manifest',lambda _:manifest)
    monkeypatch.setattr(module,'append_decision',lambda directory,payload,now:payload)
    instruments=tmp_path/'metadata.json';instruments.write_text(json.dumps(dict(records=metadata(frames))))
    account=tmp_path/'account.json';account.write_text(json.dumps(dict(simulation=True,timestamp='2026-08-31T14:05:01Z',equity=100000,shares=dict.fromkeys(FOUR,0))))
    r=module.record(tmp_path,bars,instruments,account,now='2026-08-31T14:05:03Z')
    assert {t['horizon'] for t in r['training']}=={1}
    assert all(t['last_train']<'2026-08-31' for t in r['training'])
    assert set(r['selection']['selections'])==set(FOUR)
    assert all(f['last_train']<f['validation_day']<'2026-08-31' for f in r['selection']['folds'])
    assert r['pnl'] is None and r['orders_submitted']==0
    assert set(r['explanation']['stock_models'])==set(FOUR)
    with pytest.raises(ValueError,match='Fresh future'):
        module.record(tmp_path,bars,instruments,account,now='2026-09-13T14:05:03Z')
