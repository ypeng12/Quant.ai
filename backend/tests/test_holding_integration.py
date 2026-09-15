from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from test_research_execution import runner_type, bars
from app.research.holding_policy import HoldingSpec
from app.research.holding_l1 import HoldingL1Residual,packet_books,apply_residuals,CONTRACT
from app.alpha.paper_l1_alpha import PAPER_L1_FEATURES,VERSION


def test_new_model_reaches_integer_order_chain_and_reference_is_not_traded(runner_type):
    runner=runner_type.__new__(runner_type);calls=[];seen=[]
    spec=HoldingSpec(horizons=(1,),planning=False)
    def target(frames,current,**kwargs):
        seen.append(set(frames))
        return {'A':.4},dict(cumulative_forecast_bps={'A':{'5':10.}},l1_contributes=False,active_features=58)
    runner.adapter=SimpleNamespace(is_paper=True,get_clock=lambda:dict(success=True,is_open=True,
        timestamp='2026-09-14T10:05:00-04:00',next_close='2026-09-14T16:00:00-04:00'),
        client=SimpleNamespace(get_asset=lambda s:SimpleNamespace(shortable=True)),
        submit_market_order=lambda *a,**k:calls.append(a) or dict(success=True,status='accepted',order_id='accepted'))
    runner.strategy_params=runner_type._quant_policy_defaults()
    runner._quant_broker_snapshot=lambda:([],[],dict(equity=1000.,buying_power=1000.,shorting_enabled=True))
    runner._quant_model=lambda:SimpleNamespace(symbols=('A',),input_symbols=('A','SPY'),trained_before='2026-09-12',spec=spec,live_target=target)
    runner._quant_model_key=('new-model',1);runner._quant_last_bar=None
    runner._quant_submissions={};runner._quant_status={};runner.trade_history=[];runner.add_log=lambda m:None
    runner._run_quant_policy_cycle()
    assert seen==[{'A','SPY'}]
    assert calls==[('A',4,'buy')]
    assert runner.trade_history==[]
    assert runner._quant_status['decision_diagnostics']['active_features']==58


def l1_book():
    index=pd.date_range('2026-09-11 09:30',periods=78,freq='5min',tz='America/New_York')
    rng=np.random.default_rng(5)
    b=pd.DataFrame(rng.normal(size=(78,len(PAPER_L1_FEATURES))),index=index,columns=PAPER_L1_FEATURES)
    b.attrs.update(symbol='SNDK',feed='iex',source='alpaca_stock_historical',clock='historical_exchange_latency_unverified',
                   quote_size_unit='round_lots',feature_version=VERSION)
    return b


def test_learned_l1_residual_uses_only_mature_prior_oos_errors(tmp_path):
    b=l1_book();base=pd.Series(0.,index=b.index);target=b.iloc[:,0]*.001
    ends=pd.Series(b.index+pd.Timedelta(minutes=10),index=b.index)
    trained=pd.Series(pd.Timestamp('2026-09-11',tz='America/New_York'),index=b.index)
    m=HoldingL1Residual().fit(b,base,target,ends,before=pd.Timestamp('2026-09-14',tz='America/New_York'),base_trained_before=trained)
    p=tmp_path/'model.json';m.save(p);restored=HoldingL1Residual.load(p)
    future=b.iloc[[0]].copy();future.index=pd.DatetimeIndex([pd.Timestamp('2026-09-14 09:30',tz='America/New_York')])
    assert restored.adjustment(future,pd.Timestamp('2026-09-14 09:35',tz='America/New_York'))==pytest.approx(m.adjustment(future,pd.Timestamp('2026-09-14 09:35',tz='America/New_York')))
    future.attrs['clock']='recorded_arrival'
    adjustment,status=apply_residuals({'SNDK':m},{'SNDK':future},pd.Timestamp('2026-09-14 09:35',tz='America/New_York'),['SNDK'])
    assert adjustment['SNDK']==0 and status['SNDK']['state']=='base_only'
    trained[:]=pd.Timestamp('2026-09-12',tz='America/New_York')
    with pytest.raises(ValueError):HoldingL1Residual().fit(b,base,target,ends,before=pd.Timestamp('2026-09-14',tz='America/New_York'),base_trained_before=trained)


def test_l1_packet_cannot_arrive_from_the_future():
    b=l1_book();packet=dict(bar_time='2026-09-14T09:30:00-04:00',available_at='2026-09-14T09:35:01-04:00',
        symbols={'SNDK':dict(contract=b.attrs,features=b.iloc[0].to_dict())})
    with pytest.raises(ValueError):packet_books(packet,pd.Timestamp('2026-09-14T09:35:00-04:00'))
    assert 'SNDK' in packet_books(packet,pd.Timestamp('2026-09-14T09:35:02-04:00'))
    packet['mode']='arrival_replay_diagnostic'
    with pytest.raises(ValueError,match='Diagnostic'):
        packet_books(packet,pd.Timestamp('2026-09-14T09:35:02-04:00'))


def test_residual_cannot_be_applied_to_another_base_model():
    model=SimpleNamespace(model=SimpleNamespace(artifact={'base_model_contract':{'family':'context'}}))
    adjustment,status=apply_residuals({'SNDK':model},{},pd.Timestamp('2026-09-14T09:35:00-04:00'),
        ['SNDK'],expected_base_contract={'family':'legacy'})
    assert adjustment['SNDK']==0 and status['SNDK']['state']=='base_only'
