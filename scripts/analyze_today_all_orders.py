import sys, os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, 'backend'))

from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus

client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
req = GetOrdersRequest(status=QueryOrderStatus.ALL, limit=500)
orders = client.get_orders(req)
today_orders = [o for o in orders if o.filled_at and str(o.filled_at)[:10] == '2026-09-11']
print(f"Total Today Filled Orders: {len(today_orders)}")

by_sym = {}
for o in reversed(today_orders):
    sym = o.symbol
    by_sym.setdefault(sym, [])
    by_sym[sym].append(o)

total_cashflow = 0.0
total_pnl_est = {}

for sym, ords in by_sym.items():
    print(f"\n==========================================")
    print(f"=== {sym} ({len(ords)} orders) ===")
    print(f"==========================================")
    pos = 0
    cash_flow = 0.0
    for o in ords:
        qty = float(o.filled_qty)
        price = float(o.filled_avg_price)
        side = o.side.value # buy or sell
        t = str(o.filled_at)[11:19]
        if side == 'buy':
            pos += qty
            cash_flow -= qty * price
        else:
            pos -= qty
            cash_flow += qty * price
        print(f"{t} | {side.upper():4s} {qty:4.0f} shs @ ${price:7.2f} | NetPos: {pos:4.0f} | NetCashFlow: ${cash_flow:+,.2f}")
    
    total_pnl_est[sym] = cash_flow
    total_cashflow += cash_flow

print("\n==========================================")
print("=== TODAY NET CASHFLOW BY TICKER ===")
for s, cf in sorted(total_pnl_est.items(), key=lambda x: x[1]):
    print(f"{s:6s}: Cashflow = ${cf:+,.2f}")
print(f"Total Closed Cashflow: ${total_cashflow:+,.2f}")
