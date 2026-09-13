"""Reconcile simulated ledger PnL and external actual account snapshots separately."""
from __future__ import annotations
import numpy as np
import pandas as pd


def ledger_attribution(marks, fills, symbols, starting_equity):
    if marks.empty:
        raise ValueError('No marked ledger')
    records=[]
    for symbol in symbols:
        previous_shares=marks[f'{symbol}_shares'].shift(fill_value=0)
        gross=previous_shares*marks[f'{symbol}_price'].diff().fillna(0)
        for i in range(len(marks)):
            if gross.iloc[i] == 0: continue
            stamp=pd.Timestamp(marks.iloc[i].timestamp).tz_convert('America/New_York')
            records.append(dict(date=str(stamp.date()),hour=stamp.hour,symbol=symbol,
                                direction='long' if previous_shares.iloc[i]>0 else 'short',
                                gross_pnl=float(gross.iloc[i]),costs=0.))
    for fill in fills.to_dict('records'):
        stamp=pd.Timestamp(fill['fill_time']).tz_convert('America/New_York')
        before=fill['shares_after']-fill['quantity'];after=fill['shares_after']
        # Reversals have separate close/open fills in ShareLedger. Reject other ledgers.
        if before*after<0:raise ValueError('Split crossing fills before side attribution')
        direction='long' if (before if before else after)>0 else 'short'
        records.append(dict(date=str(stamp.date()),hour=stamp.hour,symbol=fill['symbol'],direction=direction,
                            gross_pnl=0.,costs=float(fill['cost'])))
    detail=pd.DataFrame(records,columns=['date','hour','symbol','direction','gross_pnl','costs'])
    detail['net_pnl']=detail.gross_pnl-detail.costs
    pnl=float(marks.equity.iloc[-1]-starting_equity)
    if not np.isclose(detail.net_pnl.sum(),pnl,atol=1e-6):raise ValueError('Marked PnL does not reconcile')
    if not np.isclose(detail.costs.sum(),marks.costs_to_date.iloc[-1],atol=1e-6):raise ValueError('Costs do not reconcile')
    result=dict(net_pnl=pnl,gross_pnl=float(detail.gross_pnl.sum()),costs=float(detail.costs.sum()),reconciled=True)
    for name,keys in [('by_symbol',['symbol']),('by_direction',['direction']),('by_day',['date']),('by_hour',['hour'])]:
        result[name]=detail.groupby(keys)[['gross_pnl','costs','net_pnl']].sum().reset_index().to_dict('records')
    return result,detail


def actual_account_reconciliation(snapshots):
    """external_flow is signed deposits minus withdrawals SINCE preceding snapshot.

    This calculates actual account equity change, including unrealized PnL. It
    cannot attribute returns to a strategy without strategy-tagged broker fills.
    """
    frame=snapshots.copy()
    stamps=pd.to_datetime(frame.timestamp,utc=True)
    if not stamps.is_monotonic_increasing or stamps.duplicated().any() or len(frame)<2:
        raise ValueError('At least two strictly ordered account snapshots required')
    if not np.isfinite(frame[['equity','external_flow']].to_numpy()).all():raise ValueError('Invalid account amounts')
    frame['net_pnl']=frame.equity.diff()-frame.external_flow
    frame.loc[frame.index[0],'net_pnl']=np.nan
    return dict(source='external_account_snapshots',net_pnl=float(frame.net_pnl.iloc[1:].sum()),
                start_equity=float(frame.equity.iloc[0]),end_equity=float(frame.equity.iloc[-1]),
                net_external_flows=float(frame.external_flow.iloc[1:].sum()),intervals=frame.iloc[1:].to_dict('records'))


def fill_tca(fills, quotes, *, tolerance='30s'):
    """Actual fills vs prior same-feed L1 midpoint; NOT consolidated NBBO TCA.

    quantity is signed; commission must be explicitly supplied (zero is valid).
    Quote price differences are slippage, not an extra fee to subtract from PnL.
    """
    rows=[]
    for symbol,group in fills.groupby('symbol'):
        q=quotes.loc[quotes.symbol==symbol].copy()
        if q.empty:raise ValueError(f'No quotes for {symbol}')
        if q.feed.nunique()!=1:raise ValueError('Do not mix feeds in TCA')
        if not np.isfinite(q[['bid_price','ask_price']]).all().all() or (q.ask_price<=q.bid_price).any() or (q.bid_price<=0).any():
            raise ValueError('Invalid or locked reference quotes')
        q['quote_time']=pd.to_datetime(q.timestamp,utc=True);q['mid']=(q.bid_price+q.ask_price)/2
        f=group.copy();f['fill_time']=pd.to_datetime(f.fill_time,utc=True)
        if not np.isfinite(f[['quantity','fill_price','commission']]).all().all() or (f.quantity==0).any() or (f.fill_price<=0).any() or (f.commission<0).any():
            raise ValueError('Invalid actual fills')
        merged=pd.merge_asof(f.sort_values('fill_time'),q[['quote_time','mid','feed']].sort_values('quote_time'),
                             left_on='fill_time',right_on='quote_time',direction='backward',
                             allow_exact_matches=False,tolerance=pd.Timedelta(tolerance))
        same_day=merged.fill_time.dt.tz_convert('America/New_York').dt.date == merged.quote_time.dt.tz_convert('America/New_York').dt.date
        merged.loc[~same_day,'mid']=np.nan
        merged['slippage_bps']=np.sign(merged.quantity)*(merged.fill_price/merged.mid-1)*10000
        merged['reference_kind']='prior_same_feed_L1_midpoint'
        rows.extend(merged.to_dict('records'))
    return pd.DataFrame(rows)
