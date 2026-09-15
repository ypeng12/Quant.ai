"""Evidence-based cost attribution. Broker fills already contain execution prices."""
import numpy as np
import pandas as pd


def cost_scenarios(gross_pnl, turnover_dollars, bps=(0.,2.,5.)):
    return [dict(one_way_bps=float(b),assumed_execution_friction=turnover_dollars*b/10000,
                 gross_pnl=gross_pnl,net_under_assumption=gross_pnl-turnover_dollars*b/10000,
                 commission_assumption=0.,actual_broker_fees=None,cost_verified=False,
                 kind='fixed_orderflow_sensitivity_not_actual_broker_deduction') for b in bps]


def audit_fills_against_quotes(fills,quotes,*,max_age_seconds=1.):
    """Compare actual fills to preceding consolidated or venue quotes.

    Signed distance to contemporaneous midpoint is effective half-spread, NOT
    implementation shortfall from decision time. Never subtract it again from PnL.
    Inputs: fill_id/symbol/side/qty/price/timestamp, and symbol/bid/ask/timestamp/feed.
    """
    rows=[]
    for fill in fills:
        row=dict(fill_id=fill['fill_id'],symbol=fill['symbol'],timestamp=fill['timestamp'],
                 status='quote_unavailable',quote_age_seconds=None,effective_half_spread_bps=None)
        t=pd.Timestamp(fill['timestamp'])
        if t.tzinfo is None: raise ValueError('Aware fill timestamp required')
        candidates=[q for q in quotes if q['symbol']==fill['symbol'] and pd.Timestamp(q['timestamp'])<=t]
        if candidates:
            q=max(candidates,key=lambda q:pd.Timestamp(q['timestamp']));age=(t-pd.Timestamp(q['timestamp'])).total_seconds()
            bid,ask,price=map(float,(q['bid'],q['ask'],fill['price']))
            if np.isfinite([bid,ask,price]).all() and 0<bid<=ask and price>0 and age<=max_age_seconds:
                if fill['side'] not in {'buy','sell'}: raise ValueError('Explicit fill side required')
                mid=(bid+ask)/2;sign=1 if fill['side']=='buy' else -1
                row.update(status='matched',quote_age_seconds=age,feed=q['feed'],
                    effective_half_spread_bps=sign*(price-mid)/mid*10000,
                    quoted_half_spread_bps=(ask-bid)/2/mid*10000,
                    notional=abs(float(fill['qty']))*price,
                    actual_commission=None,actual_regulatory_fees=None)
        rows.append(row)
    valid=[r for r in rows if r['status']=='matched']
    return dict(rows=rows,matched=len(valid),total=len(rows),actual_explicit_fees=None,
        weighted_effective_half_spread_bps=(sum(r['notional']*r['effective_half_spread_bps'] for r in valid)/sum(r['notional'] for r in valid)) if valid else None,
        interpretation='Contemporaneous price-distance diagnostic; not decision-time slippage or separate fees; do not deduct from actual fills again.')
