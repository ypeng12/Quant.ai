import sys, os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, 'backend'))

from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL
from app.broker.alpaca_adapter import AlpacaAdapter

adapter = AlpacaAdapter(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)
summary = adapter.get_account_summary()
positions = adapter.get_open_positions()

print('=== ALPACA ACCOUNT SUMMARY ===')
print(f"Equity: ${summary.get('equity', 0):,.2f}")
print(f"Cash: ${summary.get('cash', 0):,.2f}")
print(f"Buying Power: ${summary.get('buying_power', 0):,.2f}")
print(f"Today Net PnL: ${summary.get('today_pnl', 0):+,.2f}")

print('\n=== CURRENT OPEN POSITIONS ===')
for p in positions:
    sym = p.get('symbol')
    side = p.get('side')
    qty = p.get('qty')
    entry = float(p.get('avg_entry_price', 0))
    cur = float(p.get('current_price', 0))
    unrealized = float(p.get('unrealized_pl', 0))
    unrealized_pct = float(p.get('unrealized_plpc', 0))
    print(f"{sym:6s} | {side:5s} x {qty} shs | Entry: ${entry:.2f} -> Current: ${cur:.2f} | Unrealized: ${unrealized:+.2f} ({unrealized_pct*100:+.2f}%)")
