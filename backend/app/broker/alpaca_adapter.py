# backend/app/broker/alpaca_adapter.py
"""
Alpaca Broker Adapter Module
Wraps official alpaca-py SDK for paper/live trading commands.
"""

import os
from typing import Dict, List, Optional
from dotenv import load_dotenv

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus
    HAS_ALPACA_SDK = True
except ImportError:
    TradingClient = None
    MarketOrderRequest = None
    LimitOrderRequest = None
    OrderSide = None
    TimeInForce = None
    OrderStatus = None
    HAS_ALPACA_SDK = False

class AlpacaAdapter:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, base_url: Optional[str] = None):
        # Auto load .env from backend/.env or root .env
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(cur_dir)), 'backend', '.env'))
        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(cur_dir)), '.env'))
        load_dotenv()

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
            Dict containing cash, equity, buying power, today_pnl, and account status.
        """
        account = self.client.get_account()
        status_str = account.status.value if hasattr(account.status, 'value') else str(account.status)
        equity = float(account.equity)
        last_equity = float(getattr(account, 'last_equity', equity) or equity)
        today_pnl = round(equity - last_equity, 2)
        today_pnl_pct = round((today_pnl / last_equity * 100), 2) if last_equity > 0 else 0.0

        return {
            "success": True,
            "account_number": str(account.account_number),
            "status": str(status_str),
            "currency": str(account.currency),
            "cash": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "buying_power": float(account.buying_power),
            "multiplier": float(account.multiplier),
            "shorting_enabled": bool(account.shorting_enabled),
            "equity": equity,
            "last_equity": last_equity,
            "today_pnl": today_pnl,
            "today_pnl_pct": today_pnl_pct,
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

    def submit_market_order(self, symbol: str, qty: int, side: str, price: Optional[float] = None, client_order_id: Optional[str] = None) -> Dict:
        """
        Submit a market order to Alpaca.
        Args:
            symbol: Ticker symbol (e.g. 'TSLA')
            qty: Quantity of shares to buy/sell
            side: 'buy' or 'sell'
            price: Optional price hint (ignored for market orders on Alpaca API)
            client_order_id: Optional client order ID for tracking
        """
        order_side = OrderSide.BUY if side.lower() in ("buy", "cover") else OrderSide.SELL
        
        try:
            kwargs = {
                "symbol": symbol.upper(),
                "qty": qty,
                "side": order_side,
                "time_in_force": TimeInForce.DAY
            }
            if client_order_id:
                kwargs["client_order_id"] = client_order_id

            order_request = MarketOrderRequest(**kwargs)
            order = self.client.submit_order(order_data=order_request)
            return {
                "success": True,
                "order_id": str(order.id),
                "client_order_id": str(getattr(order, 'client_order_id', client_order_id or '')),
                "status": str(getattr(order.status, 'value', order.status)),
                "filled_qty": int(getattr(order, 'filled_qty', 0) or 0),
                "filled_avg_price": float(getattr(order, 'filled_avg_price', 0.0) or 0.0),
                "message": f"Successfully submitted {side.upper()} order for {qty} shares of {symbol}."
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to submit market order for {symbol}: {str(e)}"
            }

    def submit_limit_order(self, symbol: str, qty: int, side: str, limit_price: float, extended_hours: bool = True, client_order_id: Optional[str] = None) -> Dict:
        """
        Submit a Limit order to Alpaca supporting Pre-market (4:00 AM EST) and Post-market (8:00 PM EST).
        Args:
            symbol: Ticker symbol (e.g. 'TSLA')
            qty: Quantity of shares
            side: 'buy' or 'sell'
            limit_price: Limit price for execution
            extended_hours: Allow trading during pre-market / post-market extended hours
            client_order_id: Optional client order ID
        """
        order_side = OrderSide.BUY if side.lower() in ("buy", "cover") else OrderSide.SELL
        try:
            kwargs = {
                "symbol": symbol.upper(),
                "qty": qty,
                "side": order_side,
                "limit_price": round(limit_price, 2),
                "time_in_force": TimeInForce.DAY,
                "extended_hours": extended_hours
            }
            if client_order_id:
                kwargs["client_order_id"] = client_order_id

            order_request = LimitOrderRequest(**kwargs)
            order = self.client.submit_order(order_data=order_request)
            return {
                "success": True,
                "order_id": str(order.id),
                "client_order_id": str(getattr(order, 'client_order_id', client_order_id or '')),
                "status": str(getattr(order.status, 'value', order.status)),
                "filled_qty": int(getattr(order, 'filled_qty', 0) or 0),
                "filled_avg_price": float(getattr(order, 'filled_avg_price', limit_price) or limit_price),
                "message": f"Successfully submitted Extended-Hours LIMIT {side.upper()} order for {qty} shares of {symbol} at ${limit_price:.2f}."
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "message": f"Failed to submit extended hours limit order: {str(e)}"
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

    def close_position(self, symbol: str) -> Dict:
        """
        Close a specific open position for a single ticker (force liquidate/sell).
        """
        try:
            order = self.client.close_position(symbol_or_asset_id=symbol.upper())
            return {
                "success": True,
                "order_id": str(getattr(order, 'id', '')),
                "symbol": symbol.upper(),
                "message": f"Successfully submitted market order to close position for {symbol.upper()}."
            }
        except Exception as e:
            return {
                "success": False,
                "symbol": symbol.upper(),
                "error": str(e),
                "message": f"Failed to close position for {symbol.upper()}: {str(e)}"
            }

    def get_clock(self) -> Dict:
        """
        Get official exchange market clock directly from Alpaca API.
        Accounts for all US holidays, early closes, and real-time exchange status.
        """
        try:
            clock = self.client.get_clock()
            seconds_to_close = 0.0
            if clock.is_open and clock.next_close and clock.timestamp:
                seconds_to_close = (clock.next_close - clock.timestamp).total_seconds()
            return {
                "success": True,
                "is_open": bool(clock.is_open),
                "timestamp": str(clock.timestamp),
                "next_open": str(clock.next_open),
                "next_close": str(clock.next_close),
                "seconds_to_close": seconds_to_close
            }
        except Exception as e:
            return {"success": False, "error": str(e), "is_open": False, "seconds_to_close": 0.0}
