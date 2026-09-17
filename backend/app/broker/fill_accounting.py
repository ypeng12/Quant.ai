"""Read-only, account-scoped FIFO from paginated broker FILL activities.

Legacy order mirrors remain unchanged. They are not opening-inventory evidence.
This display ledger never submits/cancels orders or changes strategy decisions.
"""
from collections import defaultdict, deque
from decimal import Decimal
import copy
import os
import threading
import pandas as pd


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
    """Account view and replay share one paginated FILL collector and cache."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cache_key = None
        self.rows = None

    def snapshot(self):
        from ..dashboard.broker_replay import BROKER_REPLAY
        try:
            snapshot, message, credentials = BROKER_REPLAY.snapshot(env=os.environ)
        except ValueError:
            return None, 'credential_configuration_unavailable'
        if credentials is None:
            return None, 'credentials_unavailable'
        if snapshot is None:
            return None, 'reconciling_broker_fills'
        key = (BROKER_REPLAY.scope(credentials), snapshot['observed_at'])
        with self.lock:
            if self.cache_key != key:
                rows = activity_fifo(snapshot['events'], snapshot['positions'])
                if not snapshot.get('history_complete'):
                    for row in rows:
                        row.update(pnl=None, pnl_complete=False, accounting_status='incomplete_history')
                self.rows, self.cache_key = rows, key
            age = (pd.Timestamp.now(tz='America/New_York') - pd.Timestamp(snapshot['observed_at'])).total_seconds()
            state = 'stale_broker_fills' if snapshot.get('stale') or age > 60 else 'ready'
            return copy.deepcopy(self.rows), state


ACCOUNTING=BrokerFillAccounting()


def display_history(payload, *, snapshot=None, day=None):
    day = day or str(pd.Timestamp.now(tz='America/New_York').date())
    rows, state = ACCOUNTING.snapshot() if snapshot is None else snapshot
    result = copy.deepcopy(payload)
    legacy = result.get('trade_history', [])
    if rows is not None:
        # Full current-account history is authoritative. Unscoped order archives
        # must not be mixed with another account's verified FIFO basis.
        history = copy.deepcopy(rows)
        source = 'alpaca_fill_activity'
    else:
        history = copy.deepcopy(legacy)
        source = 'legacy_archive_pending_verification'
        for row in history:
            row.update(pnl=None, pnl_complete=False, matched_closing_qty=0,
                       unknown_basis_qty=row.get('shares', 0),
                       accounting_status='awaiting_broker_fill_reconciliation')
    result['trade_history'] = sorted(history, key=lambda r: r.get('time', ''))
    result['available_dates'] = sorted({day, *[str(r.get('date') or r.get('time', ''))[:10] for r in history if r.get('date') or r.get('time')]}, reverse=True)
    result['accounting_state'] = state
    result['history_source'] = source
    result['legacy_archive_count'] = len(legacy)
    return result


def display_summary(summary, history):
    payload = display_history({'trade_history': history}, day=summary['date'])
    rows = [r for r in payload['trade_history'] if str(r.get('date') or r.get('time', ''))[:10] == summary['date']]
    closed = [r for r in rows if r.get('pnl_complete') and r.get('matched_closing_qty', 0) > 0]
    wins = [r for r in closed if r['pnl'] > 0]
    losses = [r for r in closed if r['pnl'] < 0]
    known_realized = round(sum(r['pnl'] for r in closed), 2)
    floating = summary.get('unrealized_pnl')
    unknown = sum(not r.get('pnl_complete', False) for r in rows)
    complete = unknown == 0 and payload['accounting_state'] == 'ready'
    realized = known_realized if complete else None
    total = round(realized + floating, 2) if realized is not None and floating is not None else None
    return dict(summary, total_trades=len(rows), closed_trades=len(closed), wins=len(wins), losses=len(losses),
        win_rate=100 * len(wins) / len(closed) if closed else None, realized_pnl=realized, total_pnl=total,
        known_realized_pnl=known_realized, unknown_basis_trades=unknown, realized_pnl_complete=complete,
        best_trade=max([r['pnl'] for r in closed] + [0]) if complete else None,
        worst_trade=min([r['pnl'] for r in closed] + [0]) if complete else None,
        realized_pnl_basis='Broker FILL FIFO, account inventory reconciled; explicit fees unverified',
        accounting_state=payload['accounting_state'],
        reconciliation_difference=round(summary['alpaca_official_pnl'] - total, 2)
        if summary.get('alpaca_official_pnl') is not None and total is not None else None)
