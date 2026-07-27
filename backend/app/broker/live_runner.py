# backend/app/broker/live_runner.py
"""
Live Trading Runner Background Service
Polls real-time quotes, evaluates signals, executes trades on Alpaca, and logs decisions.
"""

import asyncio
import datetime
import os
import pytz
from typing import Dict, List, Optional
from app.broker.alpaca_adapter import AlpacaAdapter
from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL, WATCHLIST
from app.data_manager import fetch_and_prepare_data
from app.data_cache import invalidate_cache
from app.strategy import evaluate_market_state

class MockAlpacaAdapter:
    def __init__(self):
        self.cash = 100000.0
        self.equity = 100000.0
        self.positions = {}

    def get_account_summary(self) -> Dict:
        return {
            "success": True,
            "account_number": "MOCK_PAPER_9988",
            "status": "ACTIVE (本地虚拟盘)",
            "currency": "USD",
            "cash": self.cash,
            "portfolio_value": self.equity,
            "buying_power": self.cash * 2,
            "multiplier": 2.0,
            "shorting_enabled": True,
            "equity": self.equity,
            "initial_margin": 0.0,
            "maintenance_margin": 0.0,
        }

    def get_open_positions(self) -> List[Dict]:
        res = []
        for ticker, pos in self.positions.items():
            res.append({
                "ticker": ticker,
                "shares": pos["shares"],
                "avg_entry_price": pos["avg_entry_price"],
                "market_value": round(pos["shares"] * pos.get("current_price", pos["avg_entry_price"]), 2),
                "current_price": round(pos.get("current_price", pos["avg_entry_price"]), 2),
                "unrealized_pnl": round((pos.get("current_price", pos["avg_entry_price"]) - pos["avg_entry_price"]) * pos["shares"], 2),
                "unrealized_pnl_pct": round(((pos.get("current_price", pos["avg_entry_price"]) - pos["avg_entry_price"]) / pos["avg_entry_price"]) * 100, 2) if pos["avg_entry_price"] > 0 else 0.0
            })
        return res

    def get_position(self, symbol: str) -> Optional[Dict]:
        symbol = symbol.upper()
        if symbol in self.positions:
            pos = self.positions[symbol]
            return {
                "ticker": symbol,
                "shares": pos["shares"],
                "avg_entry_price": pos["avg_entry_price"],
                "market_value": round(pos["shares"] * pos.get("current_price", pos["avg_entry_price"]), 2),
                "current_price": round(pos.get("current_price", pos["avg_entry_price"]), 2),
                "unrealized_pnl": round((pos.get("current_price", pos["avg_entry_price"]) - pos["avg_entry_price"]) * pos["shares"], 2),
                "unrealized_pnl_pct": round(((pos.get("current_price", pos["avg_entry_price"]) - pos["avg_entry_price"]) / pos["avg_entry_price"]) * 100, 2) if pos["avg_entry_price"] > 0 else 0.0
            }
        return None

    def submit_market_order(self, symbol: str, qty: int, side: str) -> Dict:
        symbol = symbol.upper()
        if side.lower() == "buy":
            self.positions[symbol] = {"shares": qty, "avg_entry_price": 100.0, "current_price": 100.0}
        else:
            if symbol in self.positions:
                del self.positions[symbol]
        return {"status": "filled", "id": "mock_order_123"}

    def cancel_all_orders(self) -> Dict:
        return {"success": True, "message": "已成功撤销所有模拟挂单"}

    def close_all_positions(self) -> Dict:
        self.positions.clear()
        return {"success": True, "message": "已成功平仓所有模拟持仓"}

class LiveTradingRunner:
    def __init__(self):
        self.is_running = False
        self.logs = []
        self.active_tickers = WATCHLIST.copy()
        self.highest_prices = {}
        self.loop_task = None
        self.strategy_params = {
            "strategy_mode": "dynamic",
            "stop_loss_pct": 0.015,
            "profit_target_pct": 0.030,
            "trailing_stop_mode": "atr",
            "trailing_stop_atr_mult": 2.0,
            "rsi_threshold_buy": 70.0,
            "risk_per_trade_pct": 0.01,
            "max_position_size_pct": 0.50,
            "position_sizing_mode": "atr",
            "market_open_focus": False  # 全天候搜索高概率交易信号
        }
        self.ignore_market_hours = True  # Set to True by default to allow testing anytime
        self.adapter = MockAlpacaAdapter()

    def add_log(self, msg: str):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        full_msg = f"[{timestamp}] {msg}"
        try:
            print(full_msg)  # Print to server console
        except Exception:
            try:
                print(full_msg.encode('ascii', errors='ignore').decode('ascii'))
            except Exception:
                pass
        self.logs.append(full_msg)
        if len(self.logs) > 200:  # Restrict log size
            self.logs.pop(0)

    def start(self, strategy_params: Optional[Dict] = None, ignore_market_hours: bool = True):
        if self.is_running:
            self.add_log("【警告】量化交易机器人已在运行中。")
            return False
            
        if strategy_params:
            self.strategy_params.update(strategy_params)
            
        self.ignore_market_hours = ignore_market_hours
        
        # Initialize Adapter
        try:
            if ALPACA_API_KEY and "your_paper_api_key_here" not in ALPACA_API_KEY:
                self.adapter = AlpacaAdapter(
                    api_key=ALPACA_API_KEY,
                    api_secret=ALPACA_SECRET_KEY,
                    base_url=ALPACA_BASE_URL
                )
                self.adapter.get_account_summary()
                self.add_log("🟢 已成功连接 Alpaca 实盘/模拟盘 API。")
            else:
                self.adapter = MockAlpacaAdapter()
                self.add_log("💡 未检测到 Alpaca API Key，已自动切换至【本地虚拟模拟盘模式】。")
        except Exception as e:
            self.adapter = MockAlpacaAdapter()
            self.add_log(f"💡 连接 Alpaca 失败 ({str(e)})，已自动平滑切换至【本地虚拟模拟盘模式】。")

        self.is_running = True
        self.add_log(f"🚀 量化交易机器人已启动！监控列表: {self.active_tickers} | 策略模式: {self.strategy_params['strategy_mode']}")
        
        # Spawn async loop task safely
        try:
            loop = asyncio.get_running_loop()
            self.loop_task = loop.create_task(self._run_loop())
        except RuntimeError:
            # Fallback if called outside event loop
            pass
        return True

    def stop(self):
        if not self.is_running:
            self.add_log("【通知】量化交易机器人未处于运行状态。")
            return False
            
        self.is_running = False
        if self.loop_task:
            self.loop_task.cancel()
            self.loop_task = None
            
        self.add_log("🛑 量化交易机器人已暂停运行。")
        return True

    def get_status(self) -> Dict:
        return {
            "is_running": self.is_running,
            "ignore_market_hours": self.ignore_market_hours,
            "monitored_tickers": self.active_tickers,
            "strategy_params": self.strategy_params,
            "logs_count": len(self.logs)
        }

    def is_market_open(self) -> bool:
        """
        Check if US market is currently open (9:30 - 16:00 EST, Mon-Fri)
        """
        if self.ignore_market_hours:
            return True
            
        est = pytz.timezone('America/New_York')
        now = datetime.datetime.now(est)
        
        # Check weekday (0-4 is Mon-Fri)
        if now.weekday() > 4:
            return False
            
        market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
        
        return market_open <= now <= market_close

    async def _run_loop(self):
        while self.is_running:
            try:
                # 1. Check if market is open
                if not self.is_market_open():
                    self.add_log("💤 当前处于非交易时段，机器人处于休眠待机状态...")
                    await asyncio.sleep(60)
                    continue

                self.add_log("🔄 开始新一轮行情扫描与策略评估...")
                
                # 2. Get active positions from Alpaca to sync state
                try:
                    positions_list = self.adapter.get_open_positions()
                    positions_by_ticker = {pos['ticker']: pos for pos in positions_list}
                    # 自动将用户账户中持有的股票加入 AI 监控池
                    for pos_ticker in positions_by_ticker.keys():
                        if pos_ticker not in self.active_tickers:
                            self.active_tickers.append(pos_ticker)
                            self.add_log(f"📥 检测到已买入持仓股票 [{pos_ticker}]，已自动同步拉入 AI 策略风控与监控池。")
                except Exception as e:
                    self.add_log(f"⚠️ 无法从 Alpaca 获取当前持仓：{str(e)}，跳过本轮。")
                    await asyncio.sleep(20)
                    continue

                # 3. Poll and evaluate each stock in our watchlist
                for ticker in self.active_tickers:
                    if not self.is_running:
                        break
                        
                    try:
                        # Invalidate cache to force yfinance to fetch fresh prices
                        invalidate_cache(ticker)
                        
                        # Fetch the last few days of bars
                        try:
                            df = fetch_and_prepare_data(ticker, period="3d", interval="1m")
                        except Exception:
                            df = None
                            
                        if df is None or df.empty or len(df) < 2:
                            try:
                                df = fetch_and_prepare_data(ticker, period="5d", interval="5m")
                            except Exception:
                                df = None
                        
                        if df is None or df.empty or len(df) < 2:
                            self.add_log(f"🔍 [{ticker}] 等待最新 K 线数据更新（休眠中）")
                            continue
                            
                        # Use the last bar as current state, second-to-last as prev
                        row = df.iloc[-1]
                        prev_row = df.iloc[-2]
                        close_price = float(row['Close'])
                        
                        # Get broker position details
                        alpaca_pos = positions_by_ticker.get(ticker)
                        current_shares = alpaca_pos['shares'] if alpaca_pos else 0
                        avg_cost = alpaca_pos['avg_entry_price'] if alpaca_pos else 0.0
                        
                        # Track highest price achieved while holding for trailing stop-loss
                        if current_shares > 0:
                            highest_price = max(
                                self.highest_prices.get(ticker, avg_cost),
                                close_price
                            )
                            self.highest_prices[ticker] = highest_price
                        else:
                            highest_price = 0.0
                            if ticker in self.highest_prices:
                                del self.highest_prices[ticker]

                        # 4. Evaluate strategy actions
                        action, reason = evaluate_market_state(
                            row=row,
                            prev_row=prev_row,
                            current_shares=current_shares,
                            avg_cost=avg_cost,
                            ticker=ticker,
                            highest_price=highest_price,
                            params=self.strategy_params
                        )
                        
                        # Log status
                        regime_name = row.get('Regime', 'range_bound')
                        self.add_log(f"📊 [{ticker}] 当前价格: ${close_price:.2f} | 市场状态: {regime_name} | 持仓: {current_shares}股 | 决策: {action} ({reason})")

                        # 5. Execute action on Alpaca
                        if action == "BUY" and current_shares == 0:
                            account = self.adapter.get_account_summary()
                            total_equity = account['equity']
                            cash = account['cash']
                            
                            risk_pct = self.strategy_params.get("risk_per_trade_pct", 0.02)
                            atr_mult = self.strategy_params.get("trailing_stop_atr_mult", 1.5)
                            max_pct = self.strategy_params.get("max_position_size_pct", 0.50)
                            atr = float(row['ATR']) if 'ATR' in row and row['ATR'] > 0 else close_price * 0.02
                            
                            dollar_risk = total_equity * risk_pct
                            stop_distance = atr * atr_mult
                            
                            shares = int(dollar_risk / stop_distance) if stop_distance > 0 else int((total_equity * max_pct) / close_price)
                            max_shares = int((total_equity * max_pct) / close_price)
                            shares = min(shares, max_shares)
                            
                            cash_shares = int((cash * 0.95) / close_price)
                            shares = max(1, min(shares, cash_shares))

                            self.add_log(f"🛒 [{ticker}] 触发做多信号！发送买单：以市价买入 {shares} 股...")
                            order_res = self.adapter.submit_market_order(ticker, shares, "buy")
                            if order_res.get("success"):
                                self.add_log(f"✅ [{ticker}] 做多买单提交成功！Alpaca 订单号: {order_res.get('order_id', order_res.get('id'))}")
                                self.highest_prices[ticker] = close_price
                            else:
                                self.add_log(f"❌ [{ticker}] 做多买单提交失败。原因: {order_res.get('error')}")

                        elif action == "SHORT" and current_shares == 0:
                            account = self.adapter.get_account_summary()
                            total_equity = account['equity']
                            
                            risk_pct = self.strategy_params.get("risk_per_trade_pct", 0.02)
                            max_pct = self.strategy_params.get("max_position_size_pct", 0.50)
                            atr = float(row['ATR']) if 'ATR' in row and row['ATR'] > 0 else close_price * 0.02
                            
                            dollar_risk = total_equity * risk_pct
                            stop_distance = atr * 1.5
                            shares = int(dollar_risk / stop_distance) if stop_distance > 0 else int((total_equity * max_pct) / close_price)
                            max_shares = int((total_equity * max_pct) / close_price)
                            shares = max(1, min(shares, max_shares))

                            self.add_log(f"📉 [{ticker}] 触发做空信号！发送融券卖单：以市价融券做空 {shares} 股...")
                            order_res = self.adapter.submit_market_order(ticker, shares, "sell")
                            if order_res.get("success"):
                                self.add_log(f"✅ [{ticker}] 融券做空单提交成功！Alpaca 订单号: {order_res.get('order_id', order_res.get('id'))}")
                            else:
                                self.add_log(f"❌ [{ticker}] 融券做空单提交失败。原因: {order_res.get('error')}")

                        elif action == "SELL" and current_shares > 0:
                            self.add_log(f"🔔 [{ticker}] 触发多单平仓信号！发送卖单：以市价卖出 {current_shares} 股...")
                            order_res = self.adapter.submit_market_order(ticker, current_shares, "sell")
                            if order_res.get("success"):
                                self.add_log(f"✅ [{ticker}] 多单平仓成功！Alpaca 订单号: {order_res.get('order_id', order_res.get('id'))}")
                                if ticker in self.highest_prices:
                                    del self.highest_prices[ticker]
                            else:
                                self.add_log(f"❌ [{ticker}] 多单平仓失败。原因: {order_res.get('error')}")

                        elif action == "COVER" and current_shares < 0:
                            cover_qty = abs(current_shares)
                            self.add_log(f"🔔 [{ticker}] 触发空单平仓信号！发送买入还券单：买入 {cover_qty} 股平空...")
                            order_res = self.adapter.submit_market_order(ticker, cover_qty, "buy")
                            if order_res.get("success"):
                                self.add_log(f"✅ [{ticker}] 空单平仓成功！Alpaca 订单号: {order_res.get('order_id', order_res.get('id'))}")
                            else:
                                self.add_log(f"❌ [{ticker}] 空单平仓失败。原因: {order_res.get('error')}")
                                
                    except Exception as ex:
                        self.add_log(f"⚠️ 扫描 {ticker} 发生错误: {str(ex)}")

                # Wait for next minute (60 seconds)
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                self.add_log("Background trading loop task cancelled.")
                break
            except Exception as e:
                self.add_log(f"⚠️ 交易主循环异常: {str(e)}")
                await asyncio.sleep(30)
