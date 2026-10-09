"""Read-only, account-scoped FIFO from paginated broker FILL activities.

Legacy order mirrors remain unchanged. They are not opening-inventory evidence.
This display ledger never submits/cancels orders or changes strategy decisions.
"""
from collections import defaultdict, deque
from decimal import Decimal
import copy
import hashlib
import json
import os
import threading
import time
import pandas as pd
import requests
from .credentials import resolve_trading_credentials


def activity_fifo(activities, positions):
    queues=defaultdict(deque);orders={};seen=set();net=defaultdict(Decimal)
    for a in sorted(activities,key=lambda r:(r['transaction_time'],r['id'])):
        if a['id'] in seen:continue
        seen.add(a['id']);symbol=a['symbol'];side=1 if a['side']=='buy' else -1
        quantity=Decimal(a['qty']);price=Decimal(a['price']);remaining=quantity
        if quantity<=0 or price<=0 or a['side'] not in {'buy','sell','sell_short'}:raise ValueError('Invalid broker fill')
        stamp=pd.Timestamp(a['transaction_time']).tz_convert('America/New_York');day=str(stamp.date())
        key=(a['order_id'],day);before=net[symbol];net[symbol]+=side*quantity
        row=orders.setdefault(key,dict(order_id=a['order_id'],ticker=symbol,date=day,
            action=('COVER' if before<0 else 'BUY') if side==1 else ('SELL' if before>0 else 'SHORT'),
            quantity=Decimal(0),notional=Decimal(0),realized=Decimal(0),matched=Decimal(0),fill_ids=[]))
        row['quantity']+=quantity;row['notional']+=quantity*price;row['fill_ids'].append(a['id'])
        row['time']=stamp.strftime('%Y-%m-%d %H:%M:%S');row['broker_side']='buy' if side==1 else 'sell'
        row['order_status']='filled' if a.get('type')=='fill' else 'partially_filled'
        q=queues[symbol]
        while remaining>0 and q and q[0][0]!=side:
            entry=q[0];amount=min(remaining,entry[1]);row['realized']+=(price-entry[2])*entry[0]*amount
            row['matched']+=amount;entry[1]-=amount;remaining-=amount
            if entry[1]==0:q.popleft()
        if remaining>0:q.append([side,remaining,price])
    actual={p['symbol']:Decimal(p['qty']) for p in positions}
    mismatches={s for s in set(net)|set(actual) if abs(net[s]-actual.get(s,Decimal(0)))>Decimal('0.00000001')}
    result=[]
    for row in orders.values():
        complete=row['ticker'] not in mismatches
        result.append(dict(order_id=row['order_id'],ticker=row['ticker'],date=row['date'],time=row['time'],
            action=row['action'],broker_side=row['broker_side'],shares=float(row['quantity']),
            price=float(row['notional']/row['quantity']),pnl=float(round(row['realized'],2)) if complete else None,
            matched_closing_qty=float(row['matched']),pnl_complete=complete,
            unknown_basis_qty=0 if complete else float(row['quantity']),
            order_status=row['order_status'],source='alpaca_fill_activity',reason='Alpaca Broker Confirmed Fill',
            accounting_status='broker_activity_fifo' if complete else 'inventory_not_reconciled',
            accounting_basis='All available account FILL activities; inventory reconciled; before unverified explicit fees',
            broker_fill_ids=row['fill_ids']))
    return result


class BrokerFillAccounting:
    def __init__(self):
        self.lock=threading.Lock();self.key=None;self.running=False;self.checked=0;self.rows=None;self.events={};self.error=None
        self.last_success=None

    def snapshot(self):
        try:
            c=resolve_trading_credentials(os.environ)
        except ValueError:
            return None,'credential_configuration_unavailable'
        if c is None:return None,'credentials_unavailable'
        key=hashlib.sha256((c.endpoint+c.key).encode()).hexdigest()
        with self.lock:
            if self.key!=key:
                self.key=key;self.rows=None;self.events={};self.checked=0;self.error=None;self.last_success=None
            if not self.running and time.monotonic()-self.checked>15:
                self.running=True;threading.Thread(target=self._refresh,args=(c,key),daemon=True).start()
            state = 'reconciling_broker_fills'
            if self.rows is not None:
                state = ('ready' if self.last_success is not None and time.monotonic()-self.last_success <= 60
                         else 'stale_broker_fills')
            return copy.deepcopy(self.rows),self.error or state

    def _refresh(self,c,key):
        try:
            cache_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".runtime_state", f"fills_cache_{key[:16]}.json")
            with self.lock:events=dict(self.events) if self.key==key else {}
            if not events and os.path.exists(cache_file):
                try:
                    with open(cache_file, 'r', encoding='utf-8') as cf:
                        for a in json.load(cf).get('events', []):
                            events[a['id']] = a
                except Exception:
                    pass
            session=requests.Session();session.headers.update({'APCA-API-KEY-ID':c.key,'APCA-API-SECRET-KEY':c.secret})
            params=dict(direction='asc',page_size=100);tokens=set()
            if events:
                last=max(pd.Timestamp(a['transaction_time']) for a in events.values())
                params['after']=(last-pd.Timedelta(minutes=5)).isoformat()
            while True:
                response=session.get(c.endpoint+'/v2/account/activities/FILL',params=params,timeout=20)
                response.raise_for_status();page=response.json()
                for a in page:events[a['id']]=a
                if len(page)<100:break
                token=page[-1]['id']
                if token in tokens:raise ValueError('Repeated activity cursor')
                tokens.add(token);params['page_token']=token
            if events:
                try:
                    os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                    with open(cache_file, 'w', encoding='utf-8') as cf:
                        json.dump({'events': list(events.values())}, cf)
                except Exception:
                    pass
            response=session.get(c.endpoint+'/v2/positions',timeout=20);response.raise_for_status()
            rows=activity_fifo(list(events.values()),response.json())
            with self.lock:
                if self.key==key:
                    self.events=events;self.rows=rows;self.error=None;self.last_success=time.monotonic()
        except Exception as exc:
            with self.lock:
                if self.key==key:self.rows=None;self.error=type(exc).__name__
        finally:
            with self.lock:self.running=False;self.checked=time.monotonic()


ACCOUNTING=BrokerFillAccounting()


def display_history(payload, *, snapshot=None, day=None):
    day = day or str(pd.Timestamp.now(tz='America/New_York').date())
    rows, state = ACCOUNTING.snapshot() if snapshot is None else snapshot
    result = copy.deepcopy(payload)
    history = result.get('trade_history', [])

    if rows:
        verified_dates = {r['date'] for r in rows}
        prior = [r for r in history if str(r.get('date') or r.get('time', ''))[:10] not in verified_dates and str(r.get('date') or r.get('time', ''))[:10] != day]
        today_unverified = []
        ids = {r['order_id'] for r in rows if r['date'] == day}
        for r in history:
            if str(r.get('date') or r.get('time', ''))[:10] == day and r.get('order_id') not in ids:
                r.update(pnl=None, pnl_complete=False, matched_closing_qty=0, unknown_basis_qty=r.get('shares', 0),
                         accounting_status='awaiting_broker_fill_reconciliation')
                today_unverified.append(r)
        result['trade_history'] = sorted(prior + rows + today_unverified, key=lambda r: r.get('time', ''))
    else:
        prior = [r for r in history if str(r.get('date') or r.get('time', ''))[:10] != day]
        today = [r for r in history if str(r.get('date') or r.get('time', ''))[:10] == day]
        for r in today:
            r.update(pnl=None, pnl_complete=False, matched_closing_qty=0, unknown_basis_qty=r.get('shares', 0),
                     accounting_status='awaiting_broker_fill_reconciliation')
        result['trade_history'] = sorted(prior + today, key=lambda r: r.get('time', ''))

    result['accounting_state'] = state
    return result


def display_summary(summary,history):
    payload=display_history({'trade_history':history},day=summary['date'])
    rows=[r for r in payload['trade_history'] if str(r.get('date') or r.get('time',''))[:10]==summary['date']]
    closed=[r for r in rows if r.get('pnl_complete') and r.get('matched_closing_qty',0)>0]
    wins=[r for r in closed if r['pnl']>0];losses=[r for r in closed if r['pnl']<0]
    known_realized=round(sum(r['pnl'] for r in closed),2);floating=summary.get('unrealized_pnl')
    unknown=sum(not r.get('pnl_complete',False) for r in rows)
    complete=unknown==0 and payload['accounting_state']=='ready'
    realized=known_realized if complete else None
    total=round(realized+floating,2) if realized is not None and floating is not None else None
    return dict(summary,total_trades=len(rows),closed_trades=len(closed),wins=len(wins),losses=len(losses),
        win_rate=100*len(wins)/len(closed) if closed and complete else None,
        realized_pnl=realized,known_realized_pnl=known_realized,total_pnl=total,
        unknown_basis_trades=unknown,realized_pnl_complete=complete,
        best_trade=max([r['pnl'] for r in closed]+[0]) if complete else None,
        worst_trade=min([r['pnl'] for r in closed]+[0]) if complete else None,
        realized_pnl_basis='Broker FILL FIFO, account inventory reconciled; explicit fees unverified',
        accounting_state=payload['accounting_state'],
        reconciliation_difference=round(summary['alpaca_official_pnl']-total,2) if summary.get('alpaca_official_pnl') is not None and total is not None else None)
