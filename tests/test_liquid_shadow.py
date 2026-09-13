"""Offline paper adapter checks; synthetic inputs are not future observations."""
import importlib.util
from pathlib import Path
import sys
import json
from dataclasses import asdict
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT/'backend/tests'))
from test_liquid_policy import histories,metadata,LiquidityRules,FOUR
spec=importlib.util.spec_from_file_location('liquid_shadow',ROOT/'scripts/shadow_liquid_policy.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def fixture(tmp_path,monkeypatch):
    bars=tmp_path/'bars';bars.mkdir();frames=histories()
    for s,f in frames.items():f.to_parquet(bars/f'{s}.parquet')
    manifest=dict(registered_at='2026-08-30T21:00Z',specification=dict(candidate='largecap_four_tree',
        input_symbols=list(frames),max_data_age_seconds=300,cost_bps=5,liquidity_rules=asdict(LiquidityRules(min_adv=1))))
    monkeypatch.setattr(module,'read_manifest',lambda _:manifest)
    instruments=tmp_path/'metadata.json';meta=metadata(frames);meta['MSTR']['market_cap']=1e9
    instruments.write_text(json.dumps(dict(records=meta)))
    account=tmp_path/'account.json';account.write_text(json.dumps(dict(simulation=True,timestamp='2026-08-31T14:05:01Z',
        equity=100000,shares={s:10 if s=='MSTR' else 0 for s in FOUR})))
    return bars,instruments,account

def test_completed_inputs_budget_ineligible_inventory_and_retain_metadata(tmp_path,monkeypatch):
    bars,instruments,account=fixture(tmp_path,monkeypatch)
    monkeypatch.setattr(module,'append_decision',lambda directory,payload,now:payload)
    r=module.record(tmp_path,bars,instruments,account,now='2026-08-31T14:05:03Z')
    assert r['available_at']=='2026-08-31T10:05:00-04:00'
    assert r['pnl'] is None and r['orders_submitted']==0
    assert r['current_weights']['MSTR']>0 and r['target_weights']['MSTR']==0
    assert not r['eligibility']['MSTR']['eligible']
    assert r['instrument_metadata_json']==instruments.read_text()
    assert all(t['last_train']<'2026-08-31' for t in r['training'])

def test_stale_inputs_real_accounts_and_unknown_exposure_are_rejected(tmp_path,monkeypatch):
    bars,instruments,account=fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='Fresh future'):
        module.record(tmp_path,bars,instruments,account,now='2026-09-13T14:00Z')
    data=json.loads(account.read_text());data['simulation']=False;account.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='simulation=true'):
        module.record(tmp_path,bars,instruments,account,now='2026-08-31T14:05:03Z')
    data['simulation']=True;data['shares']['OTHER']=5;account.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='all paper holdings'):
        module.record(tmp_path,bars,instruments,account,now='2026-08-31T14:05:03Z')
