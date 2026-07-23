# backend/app/broker/alpaca_adapter.py
"""
Alpaca Broker Adapter Module
Wraps official alpaca-py SDK for paper/live trading commands.
"""

import os
from typing import Dict, List, Optional
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus

class AlpacaAdapter:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, base_url: Optional[str] = None):
        # Load from arguments or fallback to env variables
        self.api_key = api_key or os.environ.get("ALPACA_API_KEY")
        self.api_secret = api_secret or os.environ.get("ALPACA_SECRET_KEY") or os.environ.get("ALPACA_API_SECRET")
        self.base_url = base_url or os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        
        # Determine if paper trading based on URL
        self.is_paper = "paper-api" in self.base_url
        
        if not self.api_key or not self.api_secret:
            raise ValueError("Alpaca API Credentials (Key and Secret) must be set in env or passed during initialization.")
            
        # Initialize Trading Client
        # Note: TradingClient takes api_key, api_secret, and paper parameter.
        # It handles paper vs live URL internally or respects custom URL if configured.
        self.client = TradingClient(self.api_key, self.api_secret, paper=self.is_paper)

    def get_account_summary(self) -> Dict:
        """
        Fetch broker account details.
        Returns:
            Dict containing cash, equity, buying power, and account status.
        """
        account = self.client.get_account()
        return {
            "success": True,
            "account_number": account.account_number,
            "status": account.status,
            "currency": account.currency,
            "cash": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "buying_power": float(account.buying_power),
            "multiplier": float(account.multiplier),
            "shorting_enabled": account.shorting_enabled,
            "equity": float(account.equity),
            "initial_margin": float(account.initial_margin),
            "maintenance_margin": float(account.maintenance_margin),
        }

    def get_open_positions(self) -> List[Dict]:
        """
        Fetch all active positions.
        """
        positions = self.client.get_all_positions()
        parsed_positions = []
        for pos in positions:
            parsed_positions.append({
                "ticker": pos.symbol,
                "shares": int(pos.qty),
                "avg_entry_price": float(pos.avg_entry_price),
                "market_value": float(pos.market_value),
                "current_price": float(pos.current_price),
                "unrealized_pnl": float(pos.unrealized_pl),
                "unrealized_pnl_pct": float(pos.unrealized_plpc) * 100, # Convert to %
            })
        return parsed_positions

    def get_position(self, symbol: str) -> Optional[Dict]:
        """
        Get position for a specific symbol. Returns None if not held.
        """
        try:
            pos = self.client.get_open_position(symbol.upper())
            return {
                "ticker": pos.symbol,
                "shares": int(pos.qty),
                "avg_entry_price": float(pos.avg_entry_price),
                "market_value": float(pos.market_value),
                "current_price": float(pos.current_price),
                "unrealized_pnl": float(pos.unrealized_pl),
                "unrealized_pnl_pct": float(pos.unrealized_plpc) * 100,
            }
        except Exception:
            return None

    def submit_market_order(self, symbol: str, qty: int, side: str) -> Dict:
        """
        Submit a market order to Alpaca.
        Args:
            symbol: Ticker symbol (e.g. 'TSLA')
            qty: Quantity of shares to buy/sell
            side: 'buy' or 'sell'
        """
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        
        try:
            order_request = MarketOrderRequest(
                symbol=symbol.upper(),
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.DAY
            )
            order = self.client.submit_order(order_data=order_request)
            return {
                "success": True,
                "order_id": str(order.id),
                "client_order_id": str(order.client_order_id),
                "status": str(order.status.value),
                "filled_qty": int(order.filled_qty or 0),
                "filled_avg_price": float(order.filled_avg_price or 0.0),
                "message": f"Successfully submitted {side.upper()} order for {qty} shares of {symbol}."
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to submit market order: {str(e)}"
            }

    def cancel_all_orders(self) -> Dict:
        """
        Cancel all open/pending orders.
        """
        try:
            cancel_statuses = self.client.cancel_orders()
            return {
                "success": True,
                "message": f"Submitted cancellation requests for all open orders. Statuses: {len(cancel_statuses)} orders canceled."
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

    def close_all_positions(self) -> Dict:
        """
        Close all active positions (force liquidation).
        """
        try:
            # close_all_positions returns a list of orders submitted to close positions
            close_orders = self.client.close_all_positions(cancel_orders=True)
            return {
                "success": True,
                "message": f"Submitted orders to close all positions. Initiated {len(close_orders)} closing orders."
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
