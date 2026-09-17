import copy
from app.broker.fill_accounting import activity_fifo,display_history,display_summary,ACCOUNTING


def fill(i,symbol,side,qty,price,time,order=None,kind='fill'):
    return dict(id=str(i),order_id=order or str(i),symbol=symbol,side=side,qty=str(qty),price=str(price),transaction_time=time,type=kind)


def test_partial_fills_short_basis_and_legacy_phantom_do_not_mix():
    events=[fill(1,'TSLA','sell_short',10,360.47,'2026-09-14T00:00:03Z'),
        fill(2,'SNDK','buy',16,1526.42,'2026-09-14T13:30:47Z','buy_a','partial_fill'),
        fill(3,'SNDK','buy',3,1518.55,'2026-09-14T13:31:52Z','buy_b','partial_fill'),
        fill(4,'SNDK','buy',15,1525,'2026-09-14T13:32:59Z','buy_b'),
        fill(5,'SNDK','buy',1,1529.63,'2026-09-14T13:33:40Z','buy_a'),
        fill(6,'TSLA','buy',10,360.36,'2026-09-15T00:00:01Z'),
        fill(7,'SNDK','sell',2,1562.86,'2026-09-15T00:00:09Z','sell','partial_fill'),
        fill(8,'SNDK','sell',31,1562.86,'2026-09-15T00:00:09.1Z','sell','partial_fill'),
        fill(9,'SNDK','sell',2,1562.86,'2026-09-15T00:00:09.2Z','sell')]
    result=activity_fifo(events+[events[-1]],[])
    close=next(r for r in result if r['order_id']=='sell')
    assert close['pnl']==1317.10 and close['shares']==35
    assert next(r for r in result if r['order_id']=='6')['pnl']==1.10
    original={'trade_history':[dict(time='2026-09-11 12:00',ticker='SNDK',shares=100,price=2000),
        dict(time='2026-09-14 20:00:09',ticker='SNDK',order_id='sell',pnl=-2313.43)]}
    before=copy.deepcopy(original)
    view=display_history(original,snapshot=(result,'ready'),day='2026-09-14')
    assert original==before
    assert next(r for r in view['trade_history'] if r.get('order_id')=='sell')['pnl']==1317.10


def test_inventory_disagreement_cannot_claim_known_pnl():
    result=activity_fifo([fill(1,'A','sell',1,100,'2026-09-14T14:00Z')],[])
    assert result[0]['pnl'] is None and not result[0]['pnl_complete']


def test_pending_accounting_preserves_rows_without_wrong_profit():
    data={'trade_history':[dict(time='2026-09-14 20:00:09',order_id='x',shares=35,pnl=-2313.43)]}
    r=display_history(data,snapshot=(None,'reconciling_broker_fills'),day='2026-09-14')
    assert len(r['trade_history'])==1 and r['trade_history'][0]['pnl'] is None


def test_summary_uses_the_same_account_scoped_ledger(monkeypatch):
    rows=[dict(date='2026-09-14',time='2026-09-14 20:00',ticker='SNDK',order_id='x',pnl=1317.10,pnl_complete=True,matched_closing_qty=35),
          dict(date='2026-09-14',time='2026-09-14 20:01',ticker='TSLA',order_id='y',pnl=1.10,pnl_complete=True,matched_closing_qty=10)]
    monkeypatch.setattr(ACCOUNTING,'snapshot',lambda:(rows,'ready'))
    r=display_summary(dict(date='2026-09-14',unrealized_pnl=0,alpaca_official_pnl=1318.20),[])
    assert r['realized_pnl']==1318.20 and r['wins']==2 and r['reconciliation_difference']==0


def test_snapshot_resolves_explicit_environment_and_handles_incomplete_credentials(monkeypatch):
    import app.broker.fill_accounting as module
    monkeypatch.setattr(module.os,'environ',{})
    assert module.BrokerFillAccounting().snapshot()==(None,'credentials_unavailable')
    monkeypatch.setattr(module.os,'environ',{'ALPACA_API_KEY':'test_key'})
    assert module.BrokerFillAccounting().snapshot()==(None,'credential_configuration_unavailable')


def test_all_broker_dates_replace_unscoped_archive():
    events=[fill(1,'SNDK','buy',2,100,'2026-09-14T14:00Z'),
            fill(2,'SNDK','sell',2,110,'2026-09-15T14:00Z'),
            fill(3,'TSLA','buy',1,300,'2026-09-16T14:00Z'),
            fill(4,'TSLA','sell',1,305,'2026-09-17T14:00Z')]
    rows=activity_fifo(events,[])
    archive={'trade_history':[dict(date='2026-09-11',time='2026-09-11 12:00',order_id='wrong_account',pnl=999)]}
    result=display_history(archive,snapshot=(rows,'ready'),day='2026-09-17')
    assert result['available_dates']==['2026-09-17','2026-09-16','2026-09-15','2026-09-14']
    assert len(result['trade_history'])==4
    assert all(r['order_id']!='wrong_account' for r in result['trade_history'])
    assert result['trade_history'][1]['pnl']==20
    assert archive['trade_history'][0]['pnl']==999


def test_unknown_basis_summary_never_claims_zero_realized_or_total(monkeypatch):
    rows=activity_fifo([fill(1,'SNDK','sell',2,100,'2026-09-17T14:00Z')],[])
    monkeypatch.setattr(ACCOUNTING,'snapshot',lambda:(rows,'ready'))
    s=display_summary(dict(date='2026-09-17',unrealized_pnl=420,alpaca_official_pnl=196),[])
    assert s['total_trades']==1 and s['unknown_basis_trades']==1
    assert s['realized_pnl'] is None and s['total_pnl'] is None
    assert s['best_trade'] is None and s['worst_trade'] is None
    assert s['alpaca_official_pnl']==196


def test_accounting_reuses_replay_snapshot_and_preserves_stale_rows(monkeypatch):
    import pandas as pd
    from app.dashboard.broker_replay import BROKER_REPLAY
    from app.broker.credentials import BrokerCredentials
    from app.broker.fill_accounting import BrokerFillAccounting
    c=BrokerCredentials('test_key','test_secret','https://paper-api.alpaca.markets','TEST')
    snapshot=dict(events=[fill(1,'SNDK','buy',1,100,'2026-09-15T14:00Z'),fill(2,'SNDK','sell',1,110,'2026-09-16T14:00Z')],
                  positions=[],history_complete=True,observed_at=pd.Timestamp.now(tz='UTC').isoformat(),stale=False)
    monkeypatch.setattr(BROKER_REPLAY,'snapshot',lambda env=None:(snapshot,None,c))
    view=BrokerFillAccounting();rows,state=view.snapshot()
    assert state=='ready' and rows[1]['pnl']==10
    snapshot['stale']=True
    retained,state=view.snapshot()
    assert state=='stale_broker_fills' and retained==rows
