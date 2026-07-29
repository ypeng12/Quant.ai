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
        return {"success": True, "status": "filled", "id": "mock_order_123"}

    def submit_limit_order(self, symbol: str, qty: int, side: str, limit_price: float, extended_hours: bool = True) -> Dict:
        return self.submit_market_order(symbol, qty, side, price=limit_price)

    def cancel_all_orders(self) -> Dict:
        return {"success": True, "message": "已成功撤销所有模拟挂单"}

    def close_all_positions(self) -> Dict:
        self.positions.clear()
        return {"success": True, "message": "已成功平仓所有模拟持仓"}

import json

class LiveTradingRunner:
    def __init__(self):
        self.is_running = False
        self.logs = []          # 全量日志（含扫描信息）
        self.action_logs = []   # 仅含实际买卖动作的日志
        self.trade_history = [] # 持久化交易记录（用于复盘）
        self.history_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "trade_history.json")
        self.load_trade_history()

        self.active_tickers = WATCHLIST.copy()
        self.highest_prices = {}
        self.loop_task = None
        self.strategy_params = {
            "strategy_mode": "dynamic",
            "stop_loss_pct": 0.006,          # 0.6% 止损 — 高频日内短线
            "profit_target_pct": 0.008,      # 0.8% 止盈 — 快速锁利
            "trailing_stop_mode": "atr",
            "trailing_stop_atr_mult": 1.0,   # 更紧追踪止损
            "rsi_threshold_buy": 72.0,
            "risk_per_trade_pct": 0.03,      # 每次交易风险占资金 3%，确保仓位有意义
            "max_position_size_pct": 0.50,
            "position_sizing_mode": "atr",
            "market_open_focus": False       # 全天候扫描信号
        }
        self.ignore_market_hours = True  # Set to True by default to allow testing anytime
        self.adapter = MockAlpacaAdapter()

    def load_trade_history(self):
        """从本地磁盘 trade_history.json 加载持久化交易历史，防止服务重启清空数据。"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.trade_history = data.get("trade_history", [])
                    self.action_logs = data.get("action_logs", [])
        except Exception as e:
            print(f"Error loading trade_history.json: {e}")

    def save_trade_history(self):
        """保存交易历史与动作日志到本地磁盘。"""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "trade_history": self.trade_history,
                    "action_logs": self.action_logs
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving trade_history.json: {e}")

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
        if len(self.logs) > 500:
            self.logs.pop(0)

    def add_trade_action(self, action: str, ticker: str, shares: int, price: float, reason: str, pnl: float = 0.0):
        """记录真实买卖动作到 action_logs 和 trade_history，用于 UI 显示与复盘分析。"""
        now = datetime.datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        date_str = now.strftime("%Y-%m-%d")

        # Action Feed 条目（精简版，仅展示关键买卖信息）
        action_emoji = {"BUY": "🟢", "SELL": "🔴", "SHORT": "🔻", "COVER": "🔼"}.get(action, "⚪")
        action_cn = {"BUY": "做多买入", "SELL": "多单平仓", "SHORT": "融券做空", "COVER": "空单平仓"}.get(action, action)
        pnl_str = f" | 盈亏: {'+'if pnl>=0 else ''}{pnl:.2f} USD" if pnl != 0.0 else ""
        feed_msg = f"[{timestamp_str}] {action_emoji} [{ticker}] {action_cn} × {shares}股 @ ${price:.2f}{pnl_str} | {reason}"

        self.action_logs.append(feed_msg)
        if len(self.action_logs) > 200:
            self.action_logs.pop(0)

        # 持久化交易记录（用于复盘）
        self.trade_history.append({
            "date": date_str,
            "time": timestamp_str,
            "action": action,
            "action_cn": action_cn,
            "ticker": ticker,
            "shares": shares,
            "price": round(price, 4),
            "pnl": round(pnl, 2),
            "reason": reason
        })
        if len(self.trade_history) > 1000:
            self.trade_history.pop(0)

        # 实时写入磁盘
        self.save_trade_history()

    def get_today_summary(self) -> dict:
        """统计今日交易胜负与盈亏（严格按今日日期 YYYY-MM-DD 统计真实已实现盈亏与浮动盈亏）。"""
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        today_trades = [t for t in self.trade_history if t.get("date") == today]

        closed_trades = [t for t in today_trades if t.get("action") in ("SELL", "COVER") and t.get("pnl", 0.0) != 0.0]
        wins = [t for t in closed_trades if t.get("pnl", 0.0) > 0]
        losses = [t for t in closed_trades if t.get("pnl", 0.0) < 0]
        realized_pnl = sum(t.get("pnl", 0.0) for t in closed_trades)

        # 实时计算当前在持有仓位的未实现浮动盈亏（单独统计）
        unrealized_pnl = 0.0
        try:
            open_positions = self.adapter.get_open_positions()
            for pos in open_positions:
                unrealized_pnl += pos.get("unrealized_pnl", 0.0)
        except Exception:
            pass

        return {
            "date": today,
            "total_trades": len(today_trades),
            "closed_trades": len(closed_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed_trades) * 100, 1) if closed_trades else 0.0,
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl": round(realized_pnl, 2), # 今日平仓落袋为安的真实实现盈亏
            "best_trade": round(max((t["pnl"] for t in closed_trades), default=0.0), 2),
            "worst_trade": round(min((t["pnl"] for t in closed_trades), default=0.0), 2)
        }

    def update_tickers(self, new_tickers: List[str]):
        """动态更新 AI 托管监控与研判股票池（合并用户 Watchlist 与已持有持仓股票）。"""
        if not new_tickers:
            return
        cleaned = [t.upper().strip() for t in new_tickers if t and isinstance(t, str)]
        
        # 确保当前持仓的股票始终保留在监控池中
        try:
            positions = self.adapter.get_open_positions()
            for pos in positions:
                if pos['ticker'] not in cleaned:
                    cleaned.append(pos['ticker'])
        except Exception:
            pass

        if set(cleaned) != set(self.active_tickers):
            self.active_tickers = cleaned
            self.add_log(f"🔄 AI 实时研判股票池已更新为：{self.active_tickers}")

    def start(self, strategy_params: Optional[Dict] = None, tickers: Optional[List[str]] = None, ignore_market_hours: bool = True):
        if self.is_running:
            self.add_log("【警告】量化交易机器人已在运行中。")
            return False
            
        if strategy_params:
            self.strategy_params.update(strategy_params)

        if tickers:
            self.update_tickers(tickers)
            
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
        self.add_log(f"🚀 量化交易机器人已启动！监控股票池 ({len(self.active_tickers)} 支): {self.active_tickers} | 策略模式: {self.strategy_params['strategy_mode']}")
        
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

    def submit_extended_hours_order(self, symbol: str, qty: int, side: str, limit_price: float) -> Dict:
        """下发盘前/盘后扩展时段限价挂单 (Extended-Hours Limit Order)"""
        try:
            if hasattr(self.adapter, "submit_limit_order"):
                res = self.adapter.submit_limit_order(symbol, qty, side, limit_price=limit_price, extended_hours=True)
            else:
                res = self.adapter.submit_market_order(symbol, qty, side, price=limit_price)
                
            if res.get("success"):
                action_type = "BUY" if side.lower() == "buy" else "SELL"
                self.add_log(f"🌙 [盘前/盘后限价单] 成功下发 [{symbol}] {action_type} {qty} 股 @ ${limit_price:.2f} (Extended-Hours Active)")
                self.add_trade_action(action_type, symbol, qty, limit_price, f"【盘前盘后限价交易】Limit Order @ ${limit_price:.2f}")
            return res
        except Exception as e:
            return {"success": False, "error": str(e)}

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

                self.add_log(f"📡 [{len(self.active_tickers)} 支股票] 开始本轮分析...")
                
                # 2. Get active positions from Alpaca to sync state
                try:
                    positions_list = self.adapter.get_open_positions()
                    positions_by_ticker = {pos['ticker']: pos for pos in positions_list}
                    for pos_ticker in positions_by_ticker.keys():
                        if pos_ticker not in self.active_tickers:
                            self.active_tickers.append(pos_ticker)
                            self.add_log(f"📥 检测到持仓股票 [{pos_ticker}]，已自动加入监控池。")
                except Exception as e:
                    self.add_log(f"⚠️ 无法获取 Alpaca 持仓：{str(e)}，跳过本轮。")
                    await asyncio.sleep(20)
                    continue

                # 3. Poll and evaluate each stock in our watchlist
                for ticker in self.active_tickers:
                    if not self.is_running:
                        break
                        
                    try:
                        invalidate_cache(ticker)
                        
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
                            self.add_log(f"🔍 [{ticker}] 等待 K 线数据更新...")
                            continue
                            
                        row = df.iloc[-1]
                        prev_row = df.iloc[-2]
                        close_price = float(row['Close'])
                        
                        alpaca_pos = positions_by_ticker.get(ticker)
                        current_shares = alpaca_pos['shares'] if alpaca_pos else 0
                        avg_cost = alpaca_pos['avg_entry_price'] if alpaca_pos else 0.0
                        
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

                        # 4. Evaluate strategy
                        action, reason = evaluate_market_state(
                            row=row,
                            prev_row=prev_row,
                            current_shares=current_shares,
                            avg_cost=avg_cost,
                            ticker=ticker,
                            highest_price=highest_price,
                            params=self.strategy_params
                        )

                        # ── 生成富有信息量的分析快照 ──
                        ema_9  = float(row.get('EMA_9',  close_price))
                        ema_21 = float(row.get('EMA_21', close_price))
                        vwap   = float(row.get('VWAP',   close_price))
                        rsi    = float(row.get('RSI',    50.0))
                        rvol   = float(row.get('RVOL',   1.0))
                        regime = str(row.get('Regime', 'range_bound'))

                        trend_icon = "📈" if ema_9 > ema_21 else "📉"
                        vwap_pos   = "VWAP上方✅" if close_price >= vwap else "VWAP下方⚠️"
                        ema_gap_pct = abs(ema_9 - ema_21) / ema_21 * 100

                        # 持仓状态描述
                        if current_shares > 0:
                            pnl_pct = (close_price - avg_cost) / avg_cost * 100
                            pos_label = f"多头 {current_shares}股 @ ${avg_cost:.2f} | 浮动: {'+' if pnl_pct>=0 else ''}{pnl_pct:.2f}%"
                        elif current_shares < 0:
                            pnl_pct = (avg_cost - close_price) / avg_cost * 100
                            pos_label = f"空头 {abs(current_shares)}股 @ ${avg_cost:.2f} | 浮动: {'+' if pnl_pct>=0 else ''}{pnl_pct:.2f}%"
                        else:
                            pos_label = "空仓观望"

                        # 接近触发的预警信号
                        alerts = []
                        vwap_dist_pct = abs(close_price - vwap) / vwap * 100
                        ema_cross_dist = abs(ema_9 - ema_21) / ema_21 * 100
                        if vwap_dist_pct < 0.15:
                            alerts.append("🔔 逼近VWAP生命线")
                        if ema_cross_dist < 0.08:
                            alerts.append("⚡ EMA9/21 接近交叉")
                        if rsi > 68:
                            alerts.append(f"🌡️ RSI={rsi:.0f} 超买区间")
                        if rsi < 32:
                            alerts.append(f"🌡️ RSI={rsi:.0f} 超卖区间")
                        if rvol > 1.8:
                            alerts.append(f"🔥 RVOL={rvol:.1f}x 异常放量")
                        alert_str = " | " + " · ".join(alerts) if alerts else ""

                        # 决策标注
                        if action == "HOLD":
                            decision_icon = "⏳ 观望"
                        elif action in ("BUY", "SHORT"):
                            decision_icon = f"🚀 触发 {action}"
                        else:
                            decision_icon = f"🔒 平仓 {action}"

                        snapshot = (
                            f"{trend_icon} [{ticker}] ${close_price:.2f} | "
                            f"{vwap_pos} | EMA差={ema_gap_pct:.2f}% | RSI={rsi:.0f} | "
                            f"市况={regime} | {pos_label}{alert_str} → {decision_icon}"
                        )
                        self.add_log(snapshot)


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

                            self.add_log(f"🛒 [{ticker}] 触发做多信号！以市价买入 {shares} 股...")
                            order_res = self.adapter.submit_market_order(ticker, shares, "buy")
                            if order_res.get("success"):
                                self.add_log(f"✅ [{ticker}] 做多买单成功！订单号: {order_res.get('order_id', order_res.get('id'))}")
                                self.highest_prices[ticker] = close_price
                                self.add_trade_action("BUY", ticker, shares, close_price, reason)
                            else:
                                self.add_log(f"❌ [{ticker}] 做多买单失败。原因: {order_res.get('error')}")

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

                            self.add_log(f"📉 [{ticker}] 触发做空信号！以市价融券做空 {shares} 股...")
                            order_res = self.adapter.submit_market_order(ticker, shares, "sell")
                            if order_res.get("success"):
                                self.add_log(f"✅ [{ticker}] 融券做空成功！订单号: {order_res.get('order_id', order_res.get('id'))}")
                                self.add_trade_action("SHORT", ticker, shares, close_price, reason)
                            else:
                                self.add_log(f"❌ [{ticker}] 融券做空失败。原因: {order_res.get('error')}")

                        elif action == "SELL" and current_shares > 0:
                            pnl = (close_price - avg_cost) * current_shares
                            self.add_log(f"🔔 [{ticker}] 触发多单平仓！以市价卖出 {current_shares} 股（预计盈亏 ${pnl:.2f}）...")
                            order_res = self.adapter.submit_market_order(ticker, current_shares, "sell")
                            if order_res.get("success"):
                                self.add_log(f"✅ [{ticker}] 多单平仓成功！订单号: {order_res.get('order_id', order_res.get('id'))}")
                                self.add_trade_action("SELL", ticker, current_shares, close_price, reason, pnl=pnl)
                                if ticker in self.highest_prices:
                                    del self.highest_prices[ticker]
                            else:
                                self.add_log(f"❌ [{ticker}] 多单平仓失败。原因: {order_res.get('error')}")

                        elif action == "COVER" and current_shares < 0:
                            cover_qty = abs(current_shares)
                            pnl = (avg_cost - close_price) * cover_qty
                            self.add_log(f"🔔 [{ticker}] 触发空单平仓！买入还券 {cover_qty} 股（预计盈亏 ${pnl:.2f}）...")
                            order_res = self.adapter.submit_market_order(ticker, cover_qty, "buy")
                            if order_res.get("success"):
                                self.add_log(f"✅ [{ticker}] 空单平仓成功！订单号: {order_res.get('order_id', order_res.get('id'))}")
                                self.add_trade_action("COVER", ticker, cover_qty, close_price, reason, pnl=pnl)
                            else:
                                self.add_log(f"❌ [{ticker}] 空单平仓失败。原因: {order_res.get('error')}")
                                
                    except Exception as ex:
                        self.add_log(f"⚠️ 扫描 {ticker} 发生错误: {str(ex)}")

                # 每 30 秒扫描一次，高频检验交易信号
                await asyncio.sleep(30)

            except asyncio.CancelledError:
                self.add_log("Background trading loop task cancelled.")
                break
            except Exception as e:
                self.add_log(f"⚠️ 交易主循环异常: {str(e)}")
                await asyncio.sleep(30)
