# scratch/test_alpaca.py
"""
Simple script to test Alpaca connection and print account details.
"""
import sys
import os

# Add backend directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))

from app.broker.alpaca_adapter import AlpacaAdapter
from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL

def test_connection():
    print("==================================================")
    print("       Alpaca Connection Verification Tool        ")
    print("==================================================")
    
    print(f"API Key ID: {ALPACA_API_KEY or 'Not Configured'}")
    print(f"Base URL:   {ALPACA_BASE_URL}")
    print("--------------------------------------------------")
    
    if not ALPACA_API_KEY or "your_paper_api_key_here" in ALPACA_API_KEY:
        print("[WARNING] You are using placeholder keys in backend/.env.")
        print("Please edit backend/.env and replace: ")
        print("  - your_paper_api_key_here")
        print("  - your_paper_api_secret_here")
        print("with your actual Alpaca paper trading keys from Alpaca dashboard.")
        return

    try:
        # Initialize Adapter
        print("Connecting to Alpaca API...")
        adapter = AlpacaAdapter(
            api_key=ALPACA_API_KEY,
            api_secret=ALPACA_SECRET_KEY,
            base_url=ALPACA_BASE_URL
        )
        
        # Get Account Summary
        print("Fetching account summary...")
        acc = adapter.get_account_summary()
        print("\n[SUCCESS] Connection Established!")
        print(f"  Account Number: {acc['account_number']}")
        print(f"  Account Status: {acc['status']}")
        print(f"  Currency:       {acc['currency']}")
        print(f"  Cash Balance:   ${acc['cash']:,.2f}")
        print(f"  Equity Value:   ${acc['equity']:,.2f}")
        print(f"  Buying Power:   ${acc['buying_power']:,.2f}")
        print("--------------------------------------------------")
        
        # Get Positions
        print("Fetching open positions...")
        positions = adapter.get_open_positions()
        if not positions:
            print("  No open positions found.")
        else:
            print(f"  Found {len(positions)} active positions:")
            for pos in positions:
                print(f"    - {pos['ticker']}: {pos['shares']} shares @ ${pos['avg_entry_price']:.2f} (Current: ${pos['current_price']:.2f}, PnL: ${pos['unrealized_pnl']:.2f})")
                
    except Exception as e:
        print("\n[ERROR] Connection failed!")
        print(f"Details: {str(e)}")
        print("\nSuggestions:")
        print("1. Check if your API Key and Secret are correct.")
        print("2. Ensure you are connected to the internet.")
        print("3. If using paper trading, ensure the Base URL is https://paper-api.alpaca.markets.")

if __name__ == "__main__":
    test_connection()
