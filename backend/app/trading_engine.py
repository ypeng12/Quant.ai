# backend/app/trading_engine.py

from app.config import INITIAL_CASH, SLIPPAGE_RATE, COMMISSION_PER_SHARE, MIN_COMMISSION_PER_ORDER

class Portfolio:
    def __init__(self, initial_cash=INITIAL_CASH, slippage_rate=SLIPPAGE_RATE, commission_per_share=COMMISSION_PER_SHARE, min_commission_per_order=MIN_COMMISSION_PER_ORDER):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.slippage_rate = slippage_rate
        self.commission_per_share = commission_per_share
        self.min_commission_per_order = min_commission_per_order
        self.positions = {}  # 格式: { TICKER: {"shares": int, "avg_cost": float, "highest_price": float} }
        self.ledger = []     # 详细的交易流水账
        self.realized_pnl = 0.0  # 已实现盈亏
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
        更新持仓期间达到的最高价，用于移动追踪止损。
        """
        if ticker in self.positions:
            self.positions[ticker]["highest_price"] = max(
                self.positions[ticker].get("highest_price", 0.0), 
                current_price
            )

    def get_equity(self, current_prices):
        """
        计算账户总资产 (可用资金 + 所有持仓市值)
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
        计算未实现浮动盈亏
        """
        unrealized = 0.0
        for ticker, pos in self.positions.items():
            if ticker in current_prices:
                market_price = current_prices[ticker]
                unrealized += (market_price - pos["avg_cost"]) * pos["shares"]
        return unrealized

    def calculate_position_size(self, ticker, current_price, atr, risk_pct=0.01, atr_multiplier=2.0, max_size_pct=0.5):
        """
        动态仓位管理：使用 ATR 波动率计算符合账户风险预期的买入股数。
        - 风险金额 = 账户总净资产 * (risk_pct * self.risk_multiplier)
        - 止损距离 = ATR * atr_multiplier
        - 股数 = 风险金额 / 止损距离
        - 最终股数不超过账户总净资产的 max_size_pct
        """
        total_equity = self.get_equity({ticker: current_price})
        
        # 应用账户级风控乘数
        effective_risk_pct = risk_pct * self.risk_multiplier
        if effective_risk_pct <= 0:
            return 0
            
        # 兜底：如果 ATR 异常或为 0，退化为固定比例分配
        if atr <= 0:
            target_allocation = total_equity * max_size_pct
            return int(target_allocation / current_price)
            
        dollar_risk = total_equity * effective_risk_pct
        stop_distance = atr * atr_multiplier
        
        if stop_distance <= 0:
            return 0
            
        shares = int(dollar_risk / stop_distance)
        
        # 上限控制 (MAX_POSITION_SIZE_PCT)
        max_allocation = total_equity * max_size_pct
        max_shares = int(max_allocation / current_price)
        
        return min(shares, max_shares)

    def buy(self, timestamp, ticker, price, shares):
        """
        执行买入模拟：
        1. 计入滑点：实际成交价高于盘面价格（因买入推高价格）
        2. 计算每股佣金与最低交易佣金
        """
        if shares <= 0:
            return False, "买入股数必须大于 0"

        # 计入滑点损耗 (买入时滑点拉高买入价格)
        execution_price = price * (1 + self.slippage_rate)

        # 计算佣金 (每股0.005刀，最低1刀，如果费率为0则为0)
        if self.commission_per_share <= 0:
            commission = 0.0
        else:
            commission = max(shares * self.commission_per_share, self.min_commission_per_order)
        
        # 总支出 = 股本 + 佣金
        total_cost = (execution_price * shares) + commission

        if total_cost > self.cash:
            return False, f"资金不足：需要 {total_cost:.2f} 刀，但账户只有 {self.cash:.2f} 刀。"

        # 扣除资金
        self.cash -= total_cost

        # 更新持仓和均价
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

        # 记录账单
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

        return True, f"成功在 {execution_price:.2f} 刀买入 {shares} 股 {ticker} (佣金: {commission:.2f} 刀)"

    def sell(self, timestamp, ticker, price, shares):
        """
        执行卖出/平仓模拟：
        1. 计入滑点：实际成交价低于盘面价格（因抛售拉低价格）
        2. 扣除佣金
        """
        if ticker not in self.positions:
            return False, f"账户中未持有 {ticker}"

        pos = self.positions[ticker]
        owned_shares = pos["shares"]

        # 如果卖出股数大于持有股数，自动修正为全清
        if shares > owned_shares:
            shares = owned_shares

        # 计入滑点损耗 (卖出时滑点降低卖出得到的价格)
        execution_price = price * (1 - self.slippage_rate)

        # 计算佣金
        if self.commission_per_share <= 0:
            commission = 0.0
        else:
            commission = max(shares * self.commission_per_share, self.min_commission_per_order)

        # 回笼资金 = 销售额 - 佣金
        revenue = (execution_price * shares) - commission

        # 增加资金
        self.cash += revenue

        # 计算并累加已实现利润
        pnl = (execution_price - pos["avg_cost"]) * shares
        self.realized_pnl += pnl

        # 更新/删除持仓
        if shares == owned_shares:
            del self.positions[ticker]
        else:
            self.positions[ticker]["shares"] -= shares

        # 记录账单
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

        return True, f"成功在 {execution_price:.2f} 刀卖出 {shares} 股 {ticker} (实现利润: {pnl:.2f} 刀，佣金: {commission:.2f} 刀)"

    def force_liquidate_all(self, timestamp, current_prices):
        """
        市价强制平仓所有持仓（用于每日美东 15:55 清仓或触及大额止损时）
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
                    liquidated_actions.append(msg + " (由于缺失最新价，以成本价结算)")
        
        return liquidated_actions

    def reset(self):
        """
        重置账户状态
        """
        self.cash = self.initial_cash
        self.positions = {}
        self.ledger = []
        self.realized_pnl = 0.0
        self.peak_equity = self.initial_cash
        self.risk_multiplier = 1.0
        self.consecutive_losses = 0
