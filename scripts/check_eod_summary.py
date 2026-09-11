import sys, os
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, 'backend'))

from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL
from app.broker.alpaca_adapter import AlpacaAdapter

adapter = AlpacaAdapter(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)
acc = adapter.get_account_summary()
positions = adapter.get_open_positions()

equity = acc.get('equity', 0)
today_pnl = acc.get('today_pnl', 0)
cash = acc.get('cash', 0)
buying_power = acc.get('buying_power', 0)

print(f"Equity: ${equity:,.2f}")
print(f"Today Net PnL: ${today_pnl:+,.2f}")
print(f"Cash: ${cash:,.2f}")
print(f"Buying Power: ${buying_power:,.2f}")

print("\n=== POSITIONS AT CLOSE ===")
for p in positions:
    print(f"{p.get('ticker'):6s} | {p.get('shares')} shs | avg: ${p.get('avg_entry_price', 0):.2f} | cur: ${p.get('current_price', 0):.2f} | unrl: ${p.get('unrealized_pnl', 0):+.2f} ({p.get('unrealized_pnl_pct', 0)*100:+.2f}%)")
