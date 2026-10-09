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


def test_current_account_replaces_archives_from_other_dates():
    events = [fill(1, 'SNDK', 'buy', 2, 100, '2026-09-14T14:00Z'),
              fill(2, 'SNDK', 'sell', 2, 110, '2026-09-15T14:00Z')]
    rows = activity_fifo(events, [])
    archive = {'trade_history': [dict(date='2026-09-11', time='2026-09-11 12:00',
                                      order_id='other-account', pnl=999)]}
    result = display_history(archive, snapshot=(rows, 'ready'), day='2026-09-17')
    assert [row['order_id'] for row in result['trade_history']] == ['1', '2']
    assert result['trade_history'][1]['pnl'] == 20
    assert result['available_dates'] == ['2026-09-17', '2026-09-15', '2026-09-14']
    assert result['history_source'] == 'alpaca_fill_activity'
    assert archive['trade_history'][0]['pnl'] == 999


def test_confirmed_empty_account_does_not_inherit_legacy_trades():
    archive = {'trade_history': [dict(date='2026-09-11', order_id='other-account', pnl=999)]}
    result = display_history(archive, snapshot=([], 'ready'), day='2026-09-17')
    assert result['trade_history'] == []
    assert result['available_dates'] == ['2026-09-17']
    assert result['legacy_archive_count'] == 1


def test_unavailable_broker_clears_unverified_pnl_on_all_archive_dates():
    archive = {'trade_history': [dict(date=day, time=day + ' 12:00', shares=2,
                                      pnl=999, pnl_complete=True, matched_closing_qty=2)
                                 for day in ['2026-09-11', '2026-09-17']]}
    result = display_history(archive, snapshot=(None, 'credentials_unavailable'), day='2026-09-17')
    assert len(result['trade_history']) == 2
    assert all(row['pnl'] is None and not row['pnl_complete']
               and row['matched_closing_qty'] == 0 for row in result['trade_history'])
    assert result['history_source'] == 'legacy_archive_pending_verification'
    assert all(row['pnl'] == 999 for row in archive['trade_history'])


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


def test_unavailable_fills_are_not_reported_as_zero_profit(monkeypatch):
    monkeypatch.setattr(ACCOUNTING, 'snapshot', lambda: (None, 'reconciling_broker_fills'))
    result = display_summary(dict(date='2026-10-02', unrealized_pnl=12,
                                  alpaca_official_pnl=15), [])
    assert result['realized_pnl'] is None
    assert result['known_realized_pnl'] == 0
    assert result['total_pnl'] is None
    assert result['reconciliation_difference'] is None
    assert result['alpaca_official_pnl'] == 15
    assert result['realized_pnl_complete'] is False


def test_partial_ledger_preserves_known_subtotal_without_claiming_total(monkeypatch):
    rows = [dict(date='2026-10-02', time='2026-10-02 10:00', ticker='A', order_id='a',
                 pnl=25, pnl_complete=True, matched_closing_qty=1),
            dict(date='2026-10-02', time='2026-10-02 10:05', ticker='B', order_id='b',
                 pnl=None, pnl_complete=False, matched_closing_qty=0)]
    monkeypatch.setattr(ACCOUNTING, 'snapshot', lambda: (rows, 'ready'))
    result = display_summary(dict(date='2026-10-02', unrealized_pnl=10,
                                  alpaca_official_pnl=40, known_realized_pnl=999), [])
    assert result['known_realized_pnl'] == 25
    assert result['realized_pnl'] is None and result['total_pnl'] is None
    assert result['win_rate'] is None
    assert result['unknown_basis_trades'] == 1


def test_stale_ledger_does_not_claim_current_reconciliation(monkeypatch):
    rows = [dict(date='2026-10-02', time='2026-10-02 10:00', ticker='A', order_id='a',
                 pnl=25, pnl_complete=True, matched_closing_qty=1)]
    monkeypatch.setattr(ACCOUNTING, 'snapshot', lambda: (rows, 'stale_broker_fills'))
    result = display_summary(dict(date='2026-10-02', unrealized_pnl=0,
                                  alpaca_official_pnl=25), [])
    assert result['known_realized_pnl'] == 25
    assert result['realized_pnl'] is None and result['reconciliation_difference'] is None


def test_confirmed_empty_ledger_is_genuine_zero(monkeypatch):
    monkeypatch.setattr(ACCOUNTING, 'snapshot', lambda: ([], 'ready'))
    result = display_summary(dict(date='2026-10-02', unrealized_pnl=0,
                                  alpaca_official_pnl=0), [])
    assert result['realized_pnl'] == 0 and result['total_pnl'] == 0
    assert result['realized_pnl_complete'] is True


def test_slow_refresh_exposes_stale_snapshot_instead_of_ready(monkeypatch):
    import hashlib
    import app.broker.fill_accounting as module

    monkeypatch.setattr(module.os, 'environ', {
        'ALPACA_API_KEY': 'test_key', 'ALPACA_SECRET_KEY': 'test_secret',
    })
    clock = [100.0]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    accounting = module.BrokerFillAccounting()
    accounting.key = hashlib.sha256(('https://paper-api.alpaca.markets' + 'test_key').encode()).hexdigest()
    accounting.rows = []
    accounting.running = True  # An in-flight request never advances the successful snapshot time.
    accounting.last_success = 50.0
    assert accounting.snapshot() == ([], 'ready')
    clock[0] = 111.0
    assert accounting.snapshot() == ([], 'stale_broker_fills')
