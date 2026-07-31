# backend/app/trading_engine.py

from app.config import INITIAL_CASH, SLIPPAGE_RATE, COMMISSION_PER_SHARE, MIN_COMMISSION_PER_ORDER

class Portfolio:
    def __init__(self, initial_cash=INITIAL_CASH, slippage_rate=SLIPPAGE_RATE, commission_per_share=COMMISSION_PER_SHARE, min_commission_per_order=MIN_COMMISSION_PER_ORDER):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.slippage_rate = slippage_rate
        self.commission_per_share = commission_per_share
        self.min_commission_per_order = min_commission_per_order
        self.positions = {}  # Format: { TICKER: {"shares": int, "avg_cost": float, "highest_price": float} }
        self.ledger = []     # Transaction ledger
        self.realized_pnl = 0.0  # Realized PnL
        self.peak_equity = initial_cash
        self.risk_multiplier = 1.0
        self.consecutive_losses = 0


    def get_position_shares(self, ticker):
        if ticker in self.positions:
            return self.positions[ticker]["shares"]
        return 0

    def get_position_avg_cost(self, ticker):
        if ticker in self.positions:
            return self.positions[ticker]["avg_cost"]
        return 0.0

    def get_position_highest_price(self, ticker):
        if ticker in self.positions:
            return self.positions[ticker].get("highest_price", self.positions[ticker]["avg_cost"])
        return 0.0

    def update_highest_price(self, ticker, current_price):
        """
        Update highest price reached during position hold for trailing stop-loss.
        """
        if ticker in self.positions:
            self.positions[ticker]["highest_price"] = max(
                self.positions[ticker].get("highest_price", 0.0), 
                current_price
            )

    def get_equity(self, current_prices):
        """
        Calculate total account equity (available cash + market value of all positions).
        """
        equity = self.cash
        for ticker, pos in self.positions.items():
            if ticker in current_prices:
                equity += pos["shares"] * current_prices[ticker]
            else:
                equity += pos["shares"] * pos["avg_cost"]
        return equity

    def get_unrealized_pnl(self, current_prices):
        """
        Calculate unrealized floating PnL.
        """
        unrealized = 0.0
        for ticker, pos in self.positions.items():
            if ticker in current_prices:
                market_price = current_prices[ticker]
                unrealized += (market_price - pos["avg_cost"]) * pos["shares"]
        return unrealized

    def calculate_position_size(self, ticker, current_price, atr, risk_pct=0.01, atr_multiplier=2.0, max_size_pct=0.5):
        """
        Dynamic position sizing: calculate share quantity using ATR volatility and risk per trade.
        """
        total_equity = self.get_equity({ticker: current_price})
        
        effective_risk_pct = risk_pct * self.risk_multiplier
        if effective_risk_pct <= 0:
            return 0
            
        if atr <= 0:
            target_allocation = total_equity * max_size_pct
            return int(target_allocation / current_price)
            
        dollar_risk = total_equity * effective_risk_pct
        stop_distance = atr * atr_multiplier
        
        if stop_distance <= 0:
            return 0
            
        shares = int(dollar_risk / stop_distance)
        
        max_allocation = total_equity * max_size_pct
        max_shares = int(max_allocation / current_price)
        
        return min(shares, max_shares)

    def buy(self, timestamp, ticker, price, shares):
        """
        Execute simulated BUY order with slippage and commission calculations.
        """
        if shares <= 0:
            return False, "Shares to buy must be greater than 0"

        execution_price = price * (1 + self.slippage_rate)

        if self.commission_per_share <= 0:
            commission = 0.0
        else:
            commission = max(shares * self.commission_per_share, self.min_commission_per_order)
        
        total_cost = (execution_price * shares) + commission

        if total_cost > self.cash:
            return False, f"Insufficient funds: Needs ${total_cost:.2f}, but cash available is ${self.cash:.2f}."

        self.cash -= total_cost

        if ticker in self.positions:
            pos = self.positions[ticker]
            old_shares = pos["shares"]
            old_cost = pos["avg_cost"]
            new_shares = old_shares + shares
            new_cost = ((old_shares * old_cost) + (shares * execution_price)) / new_shares
            self.positions[ticker] = {
                "shares": new_shares, 
                "avg_cost": new_cost, 
                "highest_price": max(pos.get("highest_price", 0.0), execution_price)
            }
        else:
            self.positions[ticker] = {
                "shares": shares, 
                "avg_cost": execution_price, 
                "highest_price": execution_price
            }

        self.ledger.append({
            "timestamp": str(timestamp),
            "action": "BUY",
            "ticker": ticker,
            "shares": shares,
            "market_price": round(price, 4),
            "execution_price": round(execution_price, 4),
            "commission": round(commission, 2),
            "total_value": round(execution_price * shares, 2),
            "total_cost": round(total_cost, 2),
            "cash_remaining": round(self.cash, 2)
        })

        return True, f"Successfully bought {shares} shares of {ticker} @ ${execution_price:.2f} (Commission: ${commission:.2f})"

    def sell(self, timestamp, ticker, price, shares):
        """
        Execute simulated SELL / EXIT order.
        """
        if ticker not in self.positions:
            return False, f"Ticker {ticker} not found in positions"

        pos = self.positions[ticker]
        owned_shares = pos["shares"]

        if shares > owned_shares:
            shares = owned_shares

        execution_price = price * (1 - self.slippage_rate)

        if self.commission_per_share <= 0:
            commission = 0.0
        else:
            commission = max(shares * self.commission_per_share, self.min_commission_per_order)

        revenue = (execution_price * shares) - commission

        self.cash += revenue

        pnl = (execution_price - pos["avg_cost"]) * shares
        self.realized_pnl += pnl

        if shares == owned_shares:
            del self.positions[ticker]
        else:
            self.positions[ticker]["shares"] -= shares

        self.ledger.append({
            "timestamp": str(timestamp),
            "action": "SELL",
            "ticker": ticker,
            "shares": shares,
            "market_price": round(price, 4),
            "execution_price": round(execution_price, 4),
            "commission": round(commission, 2),
            "total_value": round(execution_price * shares, 2),
            "revenue": round(revenue, 2),
            "realized_pnl": round(pnl, 2),
            "cash_remaining": round(self.cash, 2)
        })

        return True, f"Successfully sold {shares} shares of {ticker} @ ${execution_price:.2f} (Realized PnL: ${pnl:.2f}, Commission: ${commission:.2f})"

    def force_liquidate_all(self, timestamp, current_prices):
        """
        Market force liquidate all positions (EOD 15:55 or drawdown limit).
        """
        liquidated_actions = []
        tickers_to_sell = list(self.positions.keys())
        
        for ticker in tickers_to_sell:
            if ticker in current_prices:
                price = current_prices[ticker]
                shares = self.positions[ticker]["shares"]
                success, msg = self.sell(timestamp, ticker, price, shares)
                if success:
                    liquidated_actions.append(msg)
            else:
                price = self.positions[ticker]["avg_cost"]
                shares = self.positions[ticker]["shares"]
                success, msg = self.sell(timestamp, ticker, price, shares)
                if success:
                    liquidated_actions.append(msg + " (Settled at cost price due to missing quote)")
        
        return liquidated_actions

    def reset(self):
        """
        Reset account portfolio state.
        """
        self.cash = self.initial_cash
        self.positions = {}
        self.ledger = []
        self.realized_pnl = 0.0
        self.peak_equity = self.initial_cash
        self.risk_multiplier = 1.0
        self.consecutive_losses = 0
