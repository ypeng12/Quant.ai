"""Offline synthetic fixtures; never broker state or claimed future observations."""
import importlib.util
from pathlib import Path
import sys
import json
import pytest
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT/'backend/tests'))
from test_quant_policy import session
spec=importlib.util.spec_from_file_location('extended_shadow',ROOT/'scripts/shadow_extended_research.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def inputs(tmp_path,monkeypatch):
    bars=tmp_path/'bars';bars.mkdir();symbols=['SNDK','TSLA','MSTR','NVDA']
    for i,s in enumerate(symbols):
        pd.concat([session('2026-09-08',i),session('2026-09-09',i+2),session('2026-09-10',i+4)]).to_parquet(bars/f'{s}.parquet')
    manifest=dict(registered_at='2026-09-09T21:00Z',specification=dict(candidate='four_tree_h1',input_symbols=symbols,max_data_age_seconds=300,cost_bps=5))
    monkeypatch.setattr(module,'read_manifest',lambda _:manifest)
    account=tmp_path/'account.json';account.write_text(json.dumps(dict(simulation=True,timestamp='2026-09-10T14:05:01Z',equity=100000,shares=dict.fromkeys(symbols,0))))
    return bars,account

def test_future_record_uses_only_completed_input_and_never_assumes_fills(tmp_path,monkeypatch):
    bars,account=inputs(tmp_path,monkeypatch)
    observed=[]
    monkeypatch.setattr(module,'append_decision',lambda directory,payload,now:observed.append(payload) or payload)
    result=module.record(tmp_path,bars,account,now='2026-09-10T14:05:03Z')
    assert result['available_at']=='2026-09-10T10:05:00-04:00'
    assert result['pnl'] is None and result['orders_submitted']==0
    assert result['execution_status']=='decision_only_no_assumed_fills'
    assert all(t['last_train']=='2026-09-09' for t in result['training'])
    assert len(observed)==1

def test_stale_history_and_real_account_are_not_paper_validation(tmp_path,monkeypatch):
    bars,account=inputs(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='Fresh observations'):
        module.record(tmp_path,bars,account,now='2026-09-13T14:00Z')
    data=json.loads(account.read_text());data['simulation']=False;account.write_text(json.dumps(data))
    with pytest.raises(ValueError,match='simulation=true'):
        module.record(tmp_path,bars,account,now='2026-09-10T14:05:03Z')

def test_equal_benchmark_is_precommitted_before_open_not_retroactively_filled(tmp_path,monkeypatch):
    bars,account=inputs(tmp_path,monkeypatch)
    manifest=module.read_manifest(tmp_path);manifest['specification']['candidate']='four_equal'
    data=json.loads(account.read_text());data['timestamp']='2026-09-10T13:25:01Z';account.write_text(json.dumps(data))
    monkeypatch.setattr(module,'append_decision',lambda directory,payload,now:payload)
    result=module.record(tmp_path,bars,account,now='2026-09-10T13:25:03Z')
    assert result['intent']=='precommitted_0930_equal_weight'
    assert list(result['target_weights'].values())==[.95/4]*4
    assert result['forecast']=={} and result['pnl'] is None
    with pytest.raises(ValueError,match='before its intended open'):
        module.record(tmp_path,bars,account,now='2026-09-10T13:30:03Z')
