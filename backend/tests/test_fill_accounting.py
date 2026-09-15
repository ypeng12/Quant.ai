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
