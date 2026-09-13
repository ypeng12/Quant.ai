from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import hashlib
import json
import numpy as np
import pandas as pd
import pytest
from app.research.attribution import ledger_attribution,actual_account_reconciliation,fill_tca
from app.research.policy_replay import ShareLedger,ExecutionConfig
from app.research.shadow import register,append_decision,verify_log
from app.research.artifacts import load_platform_results,DEFAULT,digest
from app.research.data_audit import audit_bars,expected_sessions
from app.market_data import history
from app.market_data.alpaca_l1_capture import load_real_l1_events
from test_quant_policy import session


def test_exchange_calendar_rejects_whole_missing_day_and_accounts_for_holiday():
    assert expected_sessions('2026-09-04','2026-09-08')==['2026-09-04','2026-09-08']
    with pytest.raises(ValueError,match='missing exchange sessions'):
        audit_bars({'A':session('2026-09-08')},'2026-09-08','2026-09-09')
    with pytest.raises(ValueError,match='early-close'):
        expected_sessions('2026-11-27','2026-11-27')


def test_signed_ledger_attribution_reconciles_long_short_costs():
    ledger=ShareLedger(['A'],ExecutionConfig(slippage_bps=2));t=pd.Timestamp('2026-09-08T10:00-04:00')
    ledger.mark({'A':100},t,'open','2026-09-08')
    ledger.execute_targets({'A':10},{'A':100},t,None,'2026-09-08')
    ledger.mark({'A':110},t+pd.Timedelta(minutes=5),'close','2026-09-08')
    ledger.execute_targets({'A':-10},{'A':110},t+pd.Timedelta(minutes=5),None,'2026-09-08')
    ledger.mark({'A':105},t+pd.Timedelta(minutes=10),'close','2026-09-08')
    ledger.execute_targets({'A':0},{'A':105},t+pd.Timedelta(minutes=10),None,'2026-09-08')
    result,_=ledger_attribution(pd.DataFrame(ledger.marks),pd.DataFrame(ledger.fills),['A'],100000)
    assert result['gross_pnl']==150
    assert result['costs']==pytest.approx(.2+.22+.22+.21)
    byside={r['direction']:r for r in result['by_direction']}
    assert byside['long']['gross_pnl']==100 and byside['short']['gross_pnl']==50


def test_actual_equity_excludes_deposit_and_tca_uses_past_quotes():
    frame=pd.DataFrame(dict(timestamp=['2026-09-08T13:30Z','2026-09-08T13:35Z'],equity=[1000,1510],external_flow=[0,500]))
    assert actual_account_reconciliation(frame)['net_pnl']==10
    fills=pd.DataFrame(dict(symbol=['A'],fill_time=['2026-09-08T13:30:01Z'],quantity=[10],fill_price=[101.],commission=[0.]))
    quotes=pd.DataFrame(dict(symbol=['A','A'],timestamp=['2026-09-08T13:30:00Z','2026-09-08T13:30:01Z'],bid_price=[99.,1000.],ask_price=[101.,1002.],feed=['iex','iex']))
    tca=fill_tca(fills,quotes)
    assert tca.iloc[0].slippage_bps==pytest.approx(100.)
    stale=fill_tca(fills,quotes,tolerance='1ms')
    assert np.isnan(stale.iloc[0].slippage_bps)


def test_shadow_rejects_replay_duplicates_and_modified_log(tmp_path):
    root=tmp_path/'shadow';register(root,dict(max_data_age_seconds=300),[],now='2026-09-08T13:30Z')
    with pytest.raises(ValueError,match='future observations'):
        append_decision(root,dict(available_at='2026-09-08T13:30Z'),now='2026-09-08T13:35Z')
    payload=dict(available_at='2026-09-08T13:35Z',target_weights={'A':.1})
    append_decision(root,payload,now='2026-09-08T13:35:01Z')
    with pytest.raises(ValueError,match='duplicated'):
        append_decision(root,payload,now='2026-09-08T13:35:02Z')
    assert len(verify_log(root)[1])==1
    path=root/'decisions.jsonl';path.write_text(path.read_text().replace('0.1','0.9'))
    with pytest.raises(ValueError,match='hash chain'):verify_log(root)


def test_history_pagination_is_complete_or_explicitly_unavailable(tmp_path,monkeypatch):
    monkeypatch.setattr(history,'credentials',lambda:('test','test'))
    monkeypatch.setattr(history.time,'sleep',lambda _:None)
    class Response:
        status_code=200
        def __init__(self,payload):self.payload=payload
        def json(self):return self.payload
    class FakeSession:
        def __init__(self):self.headers={};self.calls=[]
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url,params,timeout):
            self.calls.append(params.copy())
            event=dict(t='2026-09-08T13:30:00Z',bp=100,ap=101,bs=10,**{'as':20})
            return Response(dict(quotes={'A':[event]},next_page_token='page2' if len(self.calls)==1 else None))
    monkeypatch.setattr(history.requests,'Session',FakeSession)
    directory=tmp_path/'complete'
    m=history.download_history(['A'],'2026-09-08T13:30Z','2026-09-08T14:00Z','sip','quotes',directory)
    assert m['status']=='complete' and len(m['files'])==2
    assert len(load_real_l1_events(directory,'A'))==2
    p=directory/m['normalized_files'][0]['path'];p.write_text(p.read_text()+'{}\n')
    with pytest.raises(ValueError,match='integrity'):load_real_l1_events(directory,'A')
    partial=tmp_path/'partial'
    with pytest.raises(ValueError,match='Page budget'):
        history.download_history(['A'],'2026-09-08T13:30Z','2026-09-08T14:00Z','sip','quotes',partial,max_pages=1)
    with pytest.raises(ValueError,match='incomplete'):load_real_l1_events(partial,'A')


def test_artifact_loader_rejects_mismatched_cost_even_with_updated_checksum(tmp_path):
    registry=dict(status='complete',artifact_hashes={'detail.json':hashlib.sha256(b'{}').hexdigest()},data_hashes={},data_paths={},sources={},
        trials=[dict(status='complete',cost_bps=5,summary=dict(net_pnl=8,gross_pnl=10,costs=2,starting_equity=100,ending_equity=108,turnover_dollars=10000),per_symbol={'A':dict(net_pnl=8)})])
    (tmp_path/'detail.json').write_bytes(b'{}');(tmp_path/'registry.json').write_text(json.dumps(registry))
    (tmp_path/'registry.sha256').write_text(digest(tmp_path/'registry.json'))
    result=load_platform_results(tmp_path)
    assert result['status']=='unavailable' and 'cost mismatch' in result['reason']
