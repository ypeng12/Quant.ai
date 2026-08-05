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
from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL, WATCHLIST, save_watchlist, load_watchlist
from app.data_manager import fetch_and_prepare_data
from app.data_cache import invalidate_cache
from app.strategy import evaluate_market_state, calculate_confidence_score

class MockAlpacaAdapter:
    def __init__(self):
        self.cash = 100000.0
        self.equity = 100000.0
        self.positions = {}

    def get_account_summary(self) -> Dict:
        pos_val = sum(pos["shares"] * pos.get("current_price", pos["avg_entry_price"]) for pos in self.positions.values())
        self.equity = round(self.cash + pos_val, 2)
        return {
            "success": True,
            "account_number": "MOCK_PAPER_9988",
            "status": "ACTIVE (本地虚拟盘)",
            "currency": "USD",
            "cash": round(self.cash, 2),
            "portfolio_value": self.equity,
            "buying_power": round(max(0.0, self.cash * 2), 2),
            "multiplier": 2.0,
            "shorting_enabled": True,
            "equity": self.equity,
            "initial_margin": 0.0,
            "maintenance_margin": 0.0,
        }

    def get_open_positions(self) -> List[Dict]:
        res = []
        for ticker, pos in self.positions.items():
            if pos["shares"] == 0:
                continue
            cur_p = round(pos.get("current_price", pos["avg_entry_price"]), 2)
            avg_p = pos["avg_entry_price"]
            sh = pos["shares"]
            val = round(sh * cur_p, 2)
            pnl = round((cur_p - avg_p) * sh, 2) if sh > 0 else round((avg_p - cur_p) * abs(sh), 2)
            pnl_pct = round((pnl / (abs(sh) * avg_p)) * 100.0, 2) if avg_p > 0 and sh != 0 else 0.0
            res.append({
                "ticker": ticker,
                "shares": sh,
                "avg_entry_price": avg_p,
                "market_value": val,
                "current_price": cur_p,
                "unrealized_pnl": pnl,
                "unrealized_pnl_pct": pnl_pct
            })
        return res

    def get_position(self, symbol: str) -> Optional[Dict]:
        positions = self.get_open_positions()
        for p in positions:
            if p["ticker"] == symbol.upper():
                return p
        return None

    def submit_market_order(self, symbol: str, qty: int, side: str, price: Optional[float] = None, client_order_id: Optional[str] = None) -> Dict:
        symbol = symbol.upper()
        raw_price = price if price is not None else 100.0
        slippage_pct = 0.0002
        if side.lower() in ("buy", "cover"):
            exec_price = round(raw_price * (1.0 + slippage_pct), 2)
        else:
            exec_price = round(raw_price * (1.0 - slippage_pct), 2)

        cur = self.positions.get(symbol, {"shares": 0, "avg_entry_price": exec_price, "current_price": exec_price})
        old_sh = cur["shares"]
        old_avg = cur["avg_entry_price"]

        if side.lower() == "buy":
            if old_sh >= 0:
                new_sh = old_sh + qty
                new_avg = round(((old_sh * old_avg) + (qty * exec_price)) / new_sh, 2) if new_sh > 0 else exec_price
                self.positions[symbol] = {"shares": new_sh, "avg_entry_price": new_avg, "current_price": exec_price}
                self.cash -= round(qty * exec_price, 2)
            else:
                cover_qty = min(qty, abs(old_sh))
                new_sh = old_sh + cover_qty
                pnl = (old_avg - exec_price) * cover_qty
                self.cash += round((cover_qty * old_avg) + pnl, 2)
                if new_sh == 0:
                    del self.positions[symbol]
                else:
                    self.positions[symbol] = {"shares": new_sh, "avg_entry_price": old_avg, "current_price": exec_price}

        elif side.lower() == "sell":
            if old_sh > 0:
                sell_qty = min(qty, old_sh)
                new_sh = old_sh - sell_qty
                pnl = (exec_price - old_avg) * sell_qty
                self.cash += round((sell_qty * old_avg) + pnl, 2)
                if new_sh == 0:
                    del self.positions[symbol]
                else:
                    self.positions[symbol] = {"shares": new_sh, "avg_entry_price": old_avg, "current_price": exec_price}
            else:
                new_sh = old_sh - qty
                new_avg = round(((abs(old_sh) * old_avg) + (qty * exec_price)) / abs(new_sh), 2) if new_sh != 0 else exec_price
                self.positions[symbol] = {"shares": new_sh, "avg_entry_price": new_avg, "current_price": exec_price}
                self.cash -= round(qty * exec_price, 2)

        self.get_account_summary()
        return {"success": True, "status": "filled", "id": client_order_id or f"mock_{symbol}_{int(datetime.datetime.now().timestamp())}", "exec_price": exec_price}

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
        self.config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "runner_config.json")
        self.adapter = MockAlpacaAdapter()
        self.active_tickers = WATCHLIST.copy()
        self.highest_prices = {}
        self.pending_entry_tickers = set()  # 防止重复提交建仓单 (daytrade.pdf)
        self.pending_exit_tickers = set()   # 防止重复提交平仓单 (daytrade.pdf)
        self.entry_times = {}               # 记录持仓建立时间点 (支持时间止损 daytrade.pdf)
        self.loop_task = None
        self.strategy_params = {
            "strategy_mode": "dynamic",
            "risk_per_trade_pct": 0.0030,            # 0.30% 账户风险/笔 (daytrade.pdf)
            "max_position_size_pct": 0.12,           # 单票最高 12% 账户净值占用 (daytrade.pdf)
            "daily_loss_limit_pct": 0.012,           # 当日亏损 1.20% 停止新开仓 (daytrade.pdf)
            "initial_stop_atr_mult": 1.05,           # 初始 ATR 止损倍率 (daytrade.pdf)
            "stop_min_pct": 0.0025,                  # 最小止损 0.25%
            "stop_max_pct": 0.0060,                  # 最大止损 0.60%
            "tp1_r": 0.90,                           # 第一阶止盈 0.90R (40% 减仓)
            "tp2_r": 1.60,                           # 第二阶止盈 1.60R (35% 减仓)
            "runner_size_pct": 0.25,                 # 25% Runner ATR 追踪
            "breakeven_trigger_r": 0.85,             # 0.85R 触发保本止损
            "trail_start_r": 1.10,                   # 1.10R 启动追踪止损
            "trailing_stop_atr_mult": 1.10,
            "max_hold_minutes": 35,                  # 35 分钟时间止损
            "min_reward_to_cost_ratio": 3.0          # 最小盈亏比门槛 (daytrade.pdf)
        }
        self.market_mode = "MANUAL_OPEN"     # 默认人为强制开盘，打破休市限制
        self.ignore_market_hours = True
        self.ticker_scores = {}              # AI 实时多因子置信度打分
        self.load_runner_config()
        self.add_log("📡 [系统初始化完成] Quant AI 日内风控与研判引擎已就绪...")

    def load_runner_config(self):
        """从本地磁盘 runner_config.json 加载持久化系统开盘控制模式与状态配置。"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.market_mode = data.get("market_mode", "MANUAL_OPEN")
                    if "strategy_params" in data and isinstance(data["strategy_params"], dict):
                        self.strategy_params.update(data["strategy_params"])
                    self.ignore_market_hours = (self.market_mode == "MANUAL_OPEN")
        except Exception as e:
            print(f"Error loading runner_config.json: {e}")

    def save_runner_config(self):
        """保存系统开盘控制模式与策略参数到本地磁盘 runner_config.json。"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "market_mode": self.market_mode,
                    "is_running": self.is_running,
                    "strategy_params": self.strategy_params,
                    "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving runner_config.json: {e}")

    def set_market_mode(self, mode: str) -> Dict:
        """人为设定开盘关盘控制模式: MANUAL_OPEN, MANUAL_CLOSE, AUTO_EXCHANGE"""
        mode = mode.upper().strip()
        if mode not in ("MANUAL_OPEN", "MANUAL_CLOSE", "AUTO_EXCHANGE"):
            return {"success": False, "error": f"无效的 market_mode: {mode}"}
        
        self.market_mode = mode
        if mode == "MANUAL_OPEN":
            self.ignore_market_hours = True
            msg = "🟢 [人为控制切换] 已设定为【人为开盘模式 (MANUAL_OPEN)】：允许实时研判与买卖交易！"
        elif mode == "MANUAL_CLOSE":
            self.ignore_market_hours = False
            msg = "🔴 [人为控制切换] 已设定为【人为关盘模式 (MANUAL_CLOSE)】：暂停研判扫描与交易。"
        else:
            self.ignore_market_hours = False
            msg = "⏱️ [人为控制切换] 已切换为【交易所自动模式 (AUTO_EXCHANGE)】：遵循美股官方交易时段 (9:30-16:00 EST)。"

        self.save_runner_config()
        self.add_log(msg)
        return {"success": True, "market_mode": self.market_mode, "message": msg}

    def load_trade_history(self):
        """从本地磁盘 trade_history.json 加载持久化交易历史。"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.trade_history = data.get("trade_history", [])
                    self.action_logs = data.get("action_logs", [])
                    self.recalculate_trade_pnls()
        except Exception as e:
            print(f"Error loading trade_history.json: {e}")

    def recalculate_trade_pnls(self):
        """Recalculate PnL for closed trades by matching FIFO positions across trade history (daytrade.pdf)."""
        if not self.trade_history:
            return
            
        position_tracker = {}
        self.trade_history.sort(key=lambda x: x.get("time", ""))
        
        for trade in self.trade_history:
            ticker = trade.get("ticker", "")
            action = trade.get("action", "").upper()
            qty = trade.get("shares", 0)
            price = trade.get("price", 0.0)
            
            if not ticker or qty <= 0 or price <= 0:
                continue
                
            if ticker not in position_tracker:
                position_tracker[ticker] = []
                
            if action in ("BUY", "PYRAMID_BUY"):
                position_tracker[ticker].append({"price": price, "qty": qty})
            elif action in ("SELL", "PARTIAL_SELL"):
                realized = 0.0
                remaining = qty
                queue = position_tracker[ticker]
                while remaining > 0 and queue:
                    entry = queue[0]
                    matched_qty = min(remaining, entry["qty"])
                    realized += (price - entry["price"]) * matched_qty
                    entry["qty"] -= matched_qty
                    remaining -= matched_qty
                    if entry["qty"] <= 0:
                        queue.pop(0)
                if trade.get("pnl", 0.0) == 0.0 or realized != 0.0:
                    trade["pnl"] = round(realized, 2)
            elif action in ("SHORT",):
                position_tracker[ticker].append({"price": price, "qty": -qty})
            elif action in ("COVER", "PARTIAL_COVER"):
                realized = 0.0
                remaining = qty
                queue = position_tracker[ticker]
                while remaining > 0 and queue:
                    entry = queue[0]
                    matched_qty = min(remaining, abs(entry["qty"]))
                    realized += (entry["price"] - price) * matched_qty
                    entry["qty"] += matched_qty
                    remaining -= matched_qty
                    if abs(entry["qty"]) <= 0:
                        queue.pop(0)
                if trade.get("pnl", 0.0) == 0.0 or realized != 0.0:
                    trade["pnl"] = round(realized, 2)

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
        est = pytz.timezone('America/New_York')
        timestamp = datetime.datetime.now(est).strftime("%Y-%m-%d %H:%M:%S EDT")
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
        """Record trade action to action_logs and trade_history for UI display and analysis."""
        est = pytz.timezone('America/New_York')
        now = datetime.datetime.now(est)
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
        date_str = now.strftime("%Y-%m-%d")

        # Action Feed (English)
        action_emoji = {"BUY": "🟢", "SELL": "🔴", "SHORT": "🔻", "COVER": "🔼"}.get(action, "⚪")
        action_cn = {"BUY": "BUY (Long)", "SELL": "SELL (Exit Long)", "SHORT": "SHORT (Sell Short)", "COVER": "COVER (Exit Short)"}.get(action, action)
        pnl_str = f" | PnL: {'+'if pnl>=0 else ''}{pnl:.2f} USD" if pnl != 0.0 else ""
        feed_msg = f"[{timestamp_str}] {action_emoji} [{ticker}] {action} × {shares} shs @ ${price:.2f}{pnl_str} | {reason}"

        self.action_logs.append(feed_msg)
        if len(self.action_logs) > 200:
            self.action_logs.pop(0)

        # Persistent trade history
        self.trade_history.append({
            "date": date_str,
            "time": timestamp_str,
            "action": action,
            "action_cn": action,
            "ticker": ticker,
            "shares": shares,
            "price": round(price, 4),
            "pnl": round(pnl, 2),
            "reason": reason
        })
        if len(self.trade_history) > 1000:
            self.trade_history.pop(0)

        # Save to disk
        self.save_trade_history()

    def get_today_summary(self) -> dict:
        """Calculate today's trade summary and realized/unrealized PnL."""
        self.recalculate_trade_pnls()
        est = pytz.timezone('America/New_York')
        today = datetime.datetime.now(est).strftime("%Y-%m-%d")
        today_trades = [t for t in self.trade_history if (t.get("date") or t.get("time", "")[:10]).strip() == today]

        closed_trades = [t for t in today_trades if t.get("action") in ("SELL", "COVER")]
        wins = [t for t in closed_trades if t.get("pnl", 0.0) > 0]
        losses = [t for t in closed_trades if t.get("pnl", 0.0) < 0]
        realized_pnl = sum(t.get("pnl", 0.0) for t in closed_trades)

        unrealized_pnl = 0.0
        try:
            open_positions = self.adapter.get_open_positions()
            for pos in open_positions:
                unrealized_pnl += pos.get("unrealized_pnl", 0.0)
        except Exception:
            pass

        alpaca_official_today_pnl = None
        try:
            if hasattr(self.adapter, "get_account_summary"):
                acc_info = self.adapter.get_account_summary()
                if acc_info and acc_info.get("success"):
                    alpaca_official_today_pnl = acc_info.get("today_pnl")
        except Exception:
            pass

        final_today_pnl = round(realized_pnl, 2) if (alpaca_official_today_pnl is None or alpaca_official_today_pnl == 0.0) else round(alpaca_official_today_pnl, 2)

        return {
            "date": today,
            "total_trades": len(today_trades),
            "closed_trades": len(closed_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed_trades) * 100, 1) if closed_trades else 0.0,
            "realized_pnl": round(realized_pnl, 2),
            "alpaca_official_pnl": round(alpaca_official_today_pnl, 2) if alpaca_official_today_pnl is not None else final_today_pnl,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl": round(realized_pnl + unrealized_pnl, 2),
            "best_trade": round(max((t.get("pnl", 0.0) for t in closed_trades), default=0.0), 2),
            "worst_trade": round(min((t.get("pnl", 0.0) for t in closed_trades), default=0.0), 2)
        }

    def update_tickers(self, new_tickers: List[str]):
        """Dynamically update AI monitoring universe to 100% align with user's Watchlist (Alpaca Cloud API).
        
        -------------------------------------------------------------------------
        TODO: Future AI Stock Selection Module (AI Agent Screener)
        When an AI Stock Selection agent is triggered in future releases,
        dynamically selected high-alpha stocks will be passed here to automatically
        update Alpaca's Cloud Watchlist and the live AI monitoring/trading loop.
        -------------------------------------------------------------------------
        """
        cleaned = []
        for t in new_tickers:
            if t and isinstance(t, str):
                sym = t.upper().strip()
                if sym and sym not in cleaned:
                    cleaned.append(sym)
        
        # 识别出被移除的股票，立刻自动发起 Alpaca 强行平仓全卖
        removed_tickers = [t for t in self.active_tickers if t not in cleaned]
        if removed_tickers and self.adapter:
            try:
                positions_list = self.adapter.get_open_positions()
                open_tickers = {pos['ticker']: pos for pos in positions_list}
                for r_sym in removed_tickers:
                    if r_sym in open_tickers:
                        pos = open_tickers[r_sym]
                        shares = pos.get('shares', 0)
                        self.add_log(f"🗑️ [自选股移除清仓] 检测到 [{r_sym}] 已从 Watchlist 移除，立刻自动提交 Alpaca 强行全卖清仓指令！")
                        if hasattr(self.adapter, "close_position"):
                            self.adapter.close_position(r_sym)
                        self.add_trade_action(
                            action="SELL" if shares > 0 else "COVER",
                            ticker=r_sym,
                            shares=abs(shares),
                            price=pos.get("current_price", 0.0),
                            reason="Watchlist Removal Auto Liquidation (自选股移除自动强行清仓)"
                        )
            except Exception as e:
                self.add_log(f"⚠️ 自选股移除自动清仓警告: {e}")

        if cleaned != self.active_tickers:
            self.active_tickers = cleaned
            save_watchlist(cleaned, allow_empty=True)
            self.add_log(f"🔄 AI 实时研判股票池已与 Watchlist 自动对齐并持久化保存: {self.active_tickers}")

    def close_individual_position(self, ticker: str) -> dict:
        """User force closes a single ticker position."""
        sym = ticker.upper().strip()
        try:
            if hasattr(self.adapter, "close_position"):
                res = self.adapter.close_position(sym)
                if res.get("success"):
                    self.add_log(f"⚡ [用户手动平仓] 已成功发起 {sym} 的强行卖出/平仓指令")
                    self.add_trade_action(
                        action="SELL",
                        ticker=sym,
                        shares=0,
                        price=0.0,
                        reason="User Manual Force Sell/Close"
                    )
                    return {"success": True, "message": f"Successfully submitted close order for {sym}."}
                else:
                    return {"success": False, "error": res.get("error", f"Failed to close position for {sym}")}
            else:
                return {"success": False, "error": "Broker adapter does not support closing individual positions."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def start(self, strategy_params: Optional[Dict] = None, tickers: Optional[List[str]] = None, ignore_market_hours: bool = True, market_mode: Optional[str] = None):
        if self.is_running:
            self.add_log("[Warning] 交易机器人已在运行中，无需重复启动。")
            return False

        # 人为手动启动时，自动清空上一日的旧缓存与价格高点状态
        try:
            invalidate_cache()
            self.highest_prices.clear()
            self.add_log("🧹 [手动启动重置] 已强制清空上一日盘后缓存与最高价记录，初始化全新交易周期。")
        except Exception as e:
            print(f"Cache clear warning on start: {e}")
            
        if strategy_params:
            self.strategy_params.update(strategy_params)

        if tickers:
            self.update_tickers(tickers)
            
        if market_mode:
            self.set_market_mode(market_mode)
        else:
            self.ignore_market_hours = ignore_market_hours
            if ignore_market_hours and self.market_mode != "MANUAL_CLOSE":
                self.market_mode = "MANUAL_OPEN"

        self.save_runner_config()
        
        # Initialize Adapter
        try:
            if ALPACA_API_KEY and "your_paper_api_key_here" not in ALPACA_API_KEY:
                self.adapter = AlpacaAdapter(
                    api_key=ALPACA_API_KEY,
                    api_secret=ALPACA_SECRET_KEY,
                    base_url=ALPACA_BASE_URL
                )
                self.adapter.get_account_summary()
                self.add_log("🟢 已成功连接至 Alpaca 实盘/Paper 交易接口。")
                # Sync historical closed orders from Alpaca to guarantee complete persistent log history
                self.sync_alpaca_orders_to_history()
            else:
                self.adapter = MockAlpacaAdapter()
                self.add_log("💡 未检测到 Alpaca API Key，自动切换至【本地虚拟盘模拟模式】。")
        except Exception as e:
            self.adapter = MockAlpacaAdapter()
            self.add_log(f"💡 Alpaca 连接异常 ({str(e)})，已自动降级至【本地虚拟盘模拟模式】。")
        self.is_running = True
        self.add_log(f"🤖 【AI 24/7 全自动托管开启】系统已进入无人值守全自动轮询模式！监控标的({len(self.active_tickers)}): {self.active_tickers}")
        
        # Spawn async loop task safely
        try:
            loop = asyncio.get_running_loop()
            self.loop_task = loop.create_task(self._run_loop())
        except RuntimeError:
            pass
        return True

    def sync_alpaca_orders_to_history(self):
        """自动从 Alpaca 官方接口抓取已成交的历史订单并同步存入 trade_history.json，确保历史交易永久保存。"""
        if not self.adapter or isinstance(self.adapter, MockAlpacaAdapter):
            return
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus
            req = GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=200)
            closed_orders = self.adapter.client.get_orders(filter=req)
            
            existing_ids = {t.get("order_id") for t in self.trade_history if "order_id" in t}
            added_count = 0
            for order in closed_orders:
                order_id_str = str(order.id)
                if order_id_str in existing_ids:
                    continue
                if not getattr(order, "filled_at", None):
                    continue
                
                dt = order.filled_at
                est = pytz.timezone('America/New_York')
                dt_est = dt.astimezone(est) if hasattr(dt, "astimezone") else dt
                date_str = dt_est.strftime("%Y-%m-%d")
                time_str = dt_est.strftime("%Y-%m-%d %H:%M:%S")
                action_str = order.side.value.upper() if hasattr(order.side, "value") else str(order.side).upper()
                qty = int(order.filled_qty or 0)
                price = float(order.filled_avg_price or 0.0)
                
                trade_record = {
                    "order_id": order_id_str,
                    "date": date_str,
                    "time": time_str,
                    "action": action_str,
                    "action_cn": "买入" if action_str == "BUY" else "卖出",
                    "ticker": str(order.symbol),
                    "shares": qty,
                    "price": price,
                    "pnl": 0.0,
                    "reason": "Alpaca Broker Executed Sync"
                }
                self.trade_history.append(trade_record)
                existing_ids.add(order_id_str)
                added_count += 1
                
            self.recalculate_trade_pnls()
            if added_count > 0:
                self.trade_history.sort(key=lambda x: x.get("time", ""))
                self.save_trade_history()
                self.add_log(f"📥 成功从 Alpaca 云端自动同步 {added_count} 笔历史成交记录到本地磁盘归档！")
        except Exception as e:
            print(f"Sync Alpaca orders warning: {e}")

    def stop(self):
        if not self.is_running:
            self.add_log("[Notice] AI 托管引擎处于暂停备用状态。")
            return False
            
        self.is_running = False
        if self.loop_task:
            self.loop_task.cancel()
            self.loop_task = None
            
        self.save_runner_config()
        self.add_log("🤖 【AI 引擎云端平滑重载】系统配置已同步保存，后台进程就绪中。")
        return True

    def toggle(self, strategy_params: Optional[Dict] = None, tickers: Optional[List[str]] = None) -> Dict:
        """一键人工开启 / 关闭切换 (Manual Start/Stop Toggle)"""
        if self.is_running:
            self.stop()
            return {"status": "stopped", "is_running": False, "message": "已手动关闭量化交易系统"}
        else:
            self.start(strategy_params=strategy_params, tickers=tickers)
            return {"status": "started", "is_running": True, "message": "已手动启动量化交易系统"}

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
            "market_mode": self.market_mode,
            "is_market_open": self.is_market_open(),
            "ignore_market_hours": self.ignore_market_hours,
            "ticker_scores": self.ticker_scores,
            "monitored_tickers": self.active_tickers,
            "strategy_params": self.strategy_params,
            "logs_count": len(self.logs)
        }

    def is_market_open(self) -> bool:
        """
        Check if US stock market session is open under current market mode.
        1. MANUAL_OPEN: Always return True (Forces trading system active).
        2. MANUAL_CLOSE: Always return False (Forces system paused).
        3. AUTO_EXCHANGE: Checks official Alpaca clock or NYSE schedule (9:30 AM - 4:00 PM EST).
        """
        if self.market_mode == "MANUAL_OPEN":
            return True
        if self.market_mode == "MANUAL_CLOSE":
            return False

        if self.ignore_market_hours:
            return True

        # High-precision NYSE local schedule check (Monday - Friday 9:30 AM - 4:00 PM EST)
        est = pytz.timezone('America/New_York')
        now_ny = datetime.datetime.now(est)
        is_weekday = now_ny.weekday() <= 4
        ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0
        is_regular_hours = is_weekday and (9.5 <= ny_time < 16.0)

        if hasattr(self.adapter, "get_clock"):
            clock_res = self.adapter.get_clock()
            if clock_res.get("success"):
                api_open = clock_res.get("is_open", False)
                # If API reports open or local EST time is within 9:30 AM - 4:00 PM EST on a weekday, market is open
                return api_open or is_regular_hours

        return is_regular_hours

    def check_and_trigger_eod_close(self, positions_list: list) -> bool:
        """
        日内收盘前自动强行全平持仓风控 (EOD Auto Close-All Strategy).
        Queries official exchange API `get_clock()`.
        Only triggers in the final 5 minutes of regular market hours (15:55 PM - 16:00 PM EST).
        Triggers `close_all_positions()` for 0 overnight position risk!
        """
        if not positions_list:
            return False

        est = pytz.timezone('America/New_York')
        now_ny = datetime.datetime.now(est)
        today_str = now_ny.strftime("%Y-%m-%d")

        # Weekend guard
        if now_ny.weekday() > 4:
            return False

        ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0

        # EOD liquidation must ONLY happen strictly between 15:55 PM (15.9166) and 16:00 PM (16.0) EST
        if not (15.9166 <= ny_time < 16.0):
            return False

        seconds_left = None
        if hasattr(self.adapter, "get_clock"):
            clock_res = self.adapter.get_clock()
            if clock_res.get("success"):
                if not clock_res.get("is_open"):
                    return False
                seconds_left = clock_res.get("seconds_to_close", 99999)

        # Fallback to local exchange clock math if API clock is unavailable
        if seconds_left is None:
            seconds_left = (16.0 - ny_time) * 3600.0

        if seconds_left is not None and 0.0 < seconds_left <= 300.0:
            mins_left = seconds_left / 60.0
            self.add_log(f"🌇 [交易所官方尾盘双重清场风控] 距关盘仅剩 {mins_left:.1f} 分钟！执行【双重清场】：全量撤销所有挂单 + 强行全平 {len(positions_list)} 笔持仓，确保零挂单零持仓过夜...")
            try:
                # Step 1: 撤销所有挂单，防止挂单意外成交再买入
                if hasattr(self.adapter, "cancel_all_orders"):
                    c_res = self.adapter.cancel_all_orders()
                    self.add_log(f"🧹 [双重清场 Step 1/2] 已全量撤销挂单: {c_res.get('message', 'All pending orders canceled.')}")

                # Step 2: 强行平仓所有持仓
                if hasattr(self.adapter, "close_all_positions"):
                    res = self.adapter.close_all_positions()
                    self.add_log(f"✅ [双重清场 Step 2/2] 已强行全平持仓: {res.get('message', 'All positions liquidated.')}")
                
                for pos in positions_list:
                    sym = pos.get("ticker")
                    shares = pos.get("shares", 0)
                    if sym and shares != 0:
                        self.add_trade_action(
                            action="SELL" if shares > 0 else "COVER",
                            ticker=sym,
                            shares=abs(shares),
                            price=pos.get("current_price", 0.0),
                            reason="EOD Dual Liquidation (日内收盘撤单+全平彻底不过夜)"
                        )
                return True
            except Exception as e:
                self.add_log(f"⚠️ [尾盘双重清场异常]: {str(e)}")
        return False

    async def _run_loop(self):
        while self.is_running:
            try:
                # 1. Check if market is open
                if not self.is_market_open():
                    self.add_log("💤 [休市中/未开盘] 交易所处于非常规交易时段，系统处于休市暂停模式，正在等待开盘...")
                    await asyncio.sleep(10)
                    continue

                # Check if currently in Market Opening Window (9:30 AM - 9:36 AM EST = 6:30 AM - 6:36 AM PST)
                est = pytz.timezone('America/New_York')
                now_ny = datetime.datetime.now(est)
                ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0
                is_market_opening_window = (now_ny.weekday() <= 4) and (9.50 <= ny_time < 9.60)

                if is_market_opening_window:
                    self.add_log(f"⚡ [开盘黄金重诊 6:30-6:36 PST / 9:30-9:36 EST] 开启 3 连诊高频拉网校验，防开盘漏单！监控池 [{len(self.active_tickers)} 支标的]...")
                else:
                    self.add_log(f"📡 [系统开盘中·全频段扫描] 正在研判监控池股票 [{len(self.active_tickers)} 支标的]...")
                
                # 2. Get active positions from Alpaca to sync state
                try:
                    positions_list = self.adapter.get_open_positions()
                    positions_by_ticker = {pos['ticker']: pos for pos in positions_list}
                    
                    # Clear pending order locks for updated positions
                    for pos in positions_list:
                        sym = pos['ticker']
                        if pos.get('shares', 0) != 0 and sym in self.pending_entry_tickers:
                            self.pending_entry_tickers.remove(sym)
                        elif pos.get('shares', 0) == 0 and sym in self.pending_exit_tickers:
                            self.pending_exit_tickers.remove(sym)

                    # 关盘前 15:55 EST 强行清仓不过夜
                    if self.check_and_trigger_eod_close(positions_list):
                        await asyncio.sleep(30)
                        continue

                    for pos_ticker in positions_by_ticker.keys():
                        if pos_ticker not in self.active_tickers:
                            self.active_tickers.append(pos_ticker)
                            self.add_log(f"📥 Detected active position [{pos_ticker}], added to universe.")
                except Exception as e:
                    self.add_log(f"⚠️ Failed to fetch Alpaca positions: {str(e)}, skipping round.")
                    await asyncio.sleep(20)
                    continue

                # 3. Fetch latest user watchlist and prune active_tickers
                user_watchlist = load_watchlist()
                pruned_universe = []
                for t in self.active_tickers:
                    has_pos = positions_by_ticker.get(t) and positions_by_ticker[t].get('shares', 0) != 0
                    if t in user_watchlist or has_pos:
                        pruned_universe.append(t)
                
                # Sort active tickers by live AI confidence score in descending order
                pruned_universe.sort(key=lambda t: self.ticker_scores.get(t, 0), reverse=True)
                self.active_tickers = pruned_universe

                # 4. Multi-pass Poll and evaluate each stock in our watchlist (3 passes during 6:30-6:36 PST opening window)
                scan_passes = 3 if is_market_opening_window else 1
                for pass_idx in range(scan_passes):
                    if not self.is_running:
                        break
                    if pass_idx > 0:
                        await asyncio.sleep(3)

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
                                self.add_log(f"🔍 [{ticker}] Waiting for bar data...")
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

                            # Calculate Volatility & RVOL Weighted AI Score & Relative Rank
                            ema_9 = float(row.get('EMA_9', close_price))
                            ema_21 = float(row.get('EMA_21', close_price))
                            is_bullish = (ema_9 > ema_21)
                            live_score = calculate_confidence_score(row, prev_row, is_bullish=is_bullish)
                            
                            rvol = float(row.get('RVOL', 1.0))
                            atr = float(row.get('ATR', close_price * 0.01))
                            atr_pct = (atr / close_price * 100.0) if close_price > 0 else 1.0
                            vol_multiplier = max(1.0, (rvol * 0.6) + (atr_pct * 0.4))
                            weighted_score = live_score * vol_multiplier

                            self.ticker_scores[ticker] = round(weighted_score, 1)

                            # Calculate relative rank percentile in Watchlist
                            scores_list = list(self.ticker_scores.values())
                            if scores_list:
                                rank_pct = (sum(1 for s in scores_list if s <= weighted_score) / len(scores_list)) * 100.0
                            else:
                                rank_pct = 50.0

                            # 5. Evaluate strategy with Cross-Sectional Relative Rank
                            action, reason = evaluate_market_state(
                                row=row,
                                prev_row=prev_row,
                                current_shares=current_shares,
                                avg_cost=avg_cost,
                                ticker=ticker,
                                highest_price=highest_price,
                                params=self.strategy_params,
                                rank_percentile=rank_pct
                            )

                            # Time Stop Check (daytrade.pdf P.14, 15): Exit stagnant trades after max_hold_minutes (35 mins)
                            if current_shares != 0 and ticker in self.entry_times:
                                minutes_in_trade = (datetime.datetime.now() - self.entry_times[ticker]).total_seconds() / 60.0
                                max_hold = self.strategy_params.get("max_hold_minutes", 35)
                                min_progress_r = self.strategy_params.get("time_stop_min_progress_r", 0.35)
                                stop_min_pct = self.strategy_params.get("stop_min_pct", 0.0025)
                                stop_max_pct = self.strategy_params.get("stop_max_pct", 0.0060)
                                initial_stop_atr_mult = self.strategy_params.get("initial_stop_atr_mult", 1.05)

                                atr_val = float(row['ATR']) if 'ATR' in row and row['ATR'] > 0 else close_price * 0.004
                                atr_pct = (atr_val / close_price) if close_price > 0 else 0.004
                                stop_dist_pct = min(stop_max_pct, max(stop_min_pct, initial_stop_atr_mult * atr_pct))

                                pnl_pct = (close_price - avg_cost) / avg_cost if (current_shares > 0 and avg_cost > 0) else ((avg_cost - close_price) / avg_cost if avg_cost > 0 else 0.0)
                                pnl_r = pnl_pct / stop_dist_pct if stop_dist_pct > 0 else 0.0

                                if minutes_in_trade >= max_hold and pnl_r < min_progress_r:
                                    action = "SELL" if current_shares > 0 else "COVER"
                                    reason = f"[TimeStop] Position held for {int(minutes_in_trade)} mins without reaching {min_progress_r}R progress. Closing stagnant trade."

                            # Daily Loss Limit Check (daytrade.pdf P.15, 16): Stop opening new positions if daily loss >= 1.20%
                            account_summary = self.adapter.get_account_summary()
                            total_eq = account_summary.get('equity', 100000.0)
                            daily_loss_limit_pct = self.strategy_params.get("daily_loss_limit_pct", 0.012)
                            
                            # Estimate daily unrealized + realized PnL
                            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
                            today_trades_pnl = sum(t.get("pnl", 0.0) for t in self.trade_history if t.get("date") == today_str)
                            open_pnl = sum((p.get("unrealized_pnl", 0.0)) for p in positions_list)
                            est_daily_pnl_pct = (today_trades_pnl + open_pnl) / total_eq if total_eq > 0 else 0.0

                            if est_daily_pnl_pct <= -daily_loss_limit_pct and action in ("BUY", "SHORT"):
                                action = "HOLD"
                                reason = f"[DailyLossLimit] Daily drawdown ({est_daily_pnl_pct*100:.2f}%) reached max limit (-{daily_loss_limit_pct*100:.2f}%). Blocked new entry order."

                            # Enforce Exit-Only Mode for tickers removed from user Watchlist
                            if ticker not in user_watchlist and action in ("BUY", "SHORT"):
                                action = "HOLD"
                                reason = f"[{ticker}] removed from Watchlist (Exit-Only Mode). Blocked new entry order."

                            # Deduplication Lock Check (daytrade.pdf)
                            if action in ("BUY", "SHORT") and ticker in self.pending_entry_tickers:
                                action = "HOLD"
                                reason = f"[{ticker}] Pending entry order active. Blocked duplicate entry."
                            elif action in ("SELL", "COVER", "PARTIAL_SELL", "PARTIAL_COVER") and ticker in self.pending_exit_tickers:
                                action = "HOLD"
                                reason = f"[{ticker}] Pending exit order active. Blocked duplicate exit."

                            # Generate Indicator Snapshot
                            vwap   = float(row.get('VWAP',   close_price))
                            rsi    = float(row.get('RSI',    50.0))
                            regime = str(row.get('Regime', 'range_bound'))

                            trend_icon = "📈" if ema_9 > ema_21 else "📉"
                            vwap_pos   = "Above VWAP✅" if close_price >= vwap else "Below VWAP⚠️"
                            ema_gap_pct = abs(ema_9 - ema_21) / ema_21 * 100

                            if current_shares > 0:
                                pnl_pct = (close_price - avg_cost) / avg_cost * 100
                                pos_label = f"LONG {current_shares} shs @ ${avg_cost:.2f} | PnL: {'+' if pnl_pct>=0 else ''}{pnl_pct:.2f}%"
                            elif current_shares < 0:
                                pnl_pct = (avg_cost - close_price) / avg_cost * 100
                                pos_label = f"SHORT {abs(current_shares)} shs @ ${avg_cost:.2f} | PnL: {'+' if pnl_pct>=0 else ''}{pnl_pct:.2f}%"
                            else:
                                pos_label = "📡 [系统开盘中·空仓研判] 正在全频段扫描，暂未发现符合条件的合适买点"

                            alerts = []
                            alerts.append(f"🏆 AI Score:{live_score}分")
                            vwap_dist_pct = abs(close_price - vwap) / vwap * 100
                            ema_cross_dist = abs(ema_9 - ema_21) / ema_21 * 100
                            if vwap_dist_pct < 0.15:
                                alerts.append("🔔 Near VWAP Line")
                            if ema_cross_dist < 0.08:
                                alerts.append("⚡ EMA9/21 Near Cross")
                            if rsi > 68:
                                alerts.append(f"🌡️ RSI={rsi:.0f} Overbought")
                            if rsi < 32:
                                alerts.append(f"🌡️ RSI={rsi:.0f} Oversold")
                            if rvol > 1.8:
                                alerts.append(f"🔥 RVOL={rvol:.1f}x High Vol")
                            alert_str = " | " + " · ".join(alerts) if alerts else ""

                            if action == "HOLD":
                                decision_icon = "⏳ WATCH"
                            elif action in ("BUY", "SHORT"):
                                decision_icon = f"🚀 TRIGGER {action}"
                            elif action in ("PARTIAL_SELL", "PARTIAL_COVER"):
                                decision_icon = f"🟢 PARTIAL EXIT {action}"
                            else:
                                decision_icon = f"🔒 FULL EXIT {action}"

                            snapshot = (
                                f"{trend_icon} [{ticker}] ${close_price:.2f} | "
                                f"{vwap_pos} | EMA_Diff={ema_gap_pct:.2f}% | RSI={rsi:.0f} | "
                                f"Regime={regime} | {pos_label}{alert_str} → {decision_icon}"
                            )
                            self.add_log(snapshot)

                            # 5. Execute action on Alpaca
                            if action == "BUY" and current_shares == 0:
                                account = self.adapter.get_account_summary()
                                total_equity = account['equity']
                                cash = account['cash']
                                
                                risk_pct = self.strategy_params.get("risk_per_trade_pct", 0.0030)
                                max_pct = self.strategy_params.get("max_position_size_pct", 0.12)
                                stop_min_pct = self.strategy_params.get("stop_min_pct", 0.0025)
                                stop_max_pct = self.strategy_params.get("stop_max_pct", 0.0060)
                                initial_stop_atr_mult = self.strategy_params.get("initial_stop_atr_mult", 1.05)

                                atr_val = float(row['ATR']) if 'ATR' in row and row['ATR'] > 0 else close_price * 0.004
                                atr_pct = (atr_val / close_price) if close_price > 0 else 0.004
                                stop_dist_pct = min(stop_max_pct, max(stop_min_pct, initial_stop_atr_mult * atr_pct))
                                stop_distance = close_price * stop_dist_pct

                                dollar_risk = total_equity * risk_pct
                                base_shares = int(dollar_risk / stop_distance) if stop_distance > 0 else int((total_equity * max_pct) / close_price)
                                max_shares = int((total_equity * max_pct) / close_price)
                                shares = max(1, min(base_shares, max_shares))

                                if "[Probe-Light" in reason:
                                    size_scale = 0.35
                                elif "[Standard-Entry" in reason:
                                    size_scale = 0.70
                                else:
                                    size_scale = 1.00

                                shares = int(shares * size_scale)
                                cash_shares = int((cash * 0.95) / close_price)
                                shares = max(1, min(shares, cash_shares))

                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-ENTRY"
                                self.pending_entry_tickers.add(ticker)
                                self.entry_times[ticker] = datetime.datetime.now()

                                self.add_log(f"🛒 [{ticker}] BUY signal triggered ({size_scale*100:.0f}% position, Initial Risk: ${dollar_risk:.2f})! Market buying {shares} shares...")
                                order_res = self.adapter.submit_market_order(ticker, shares, "buy", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.add_log(f"✅ [{ticker}] BUY order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.highest_prices[ticker] = close_price
                                    self.add_trade_action("BUY", ticker, shares, close_price, reason)
                                else:
                                    self.pending_entry_tickers.discard(ticker)
                                    self.add_log(f"❌ [{ticker}] BUY order failed. Reason: {order_res.get('error')}")

                            elif action == "PYRAMID_BUY" and current_shares > 0:
                                account = self.adapter.get_account_summary()
                                cash = account['cash']
                                add_shares = max(1, int(current_shares * 0.35))
                                cash_shares = int((cash * 0.90) / close_price)
                                add_shares = max(1, min(add_shares, cash_shares))

                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-PYRAMID"
                                self.add_log(f"⚡ [{ticker}] PYRAMID_BUY (顺势加仓 +35%) signal triggered! Market buying {add_shares} shares...")
                                order_res = self.adapter.submit_market_order(ticker, add_shares, "buy", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.add_log(f"✅ [{ticker}] PYRAMID_BUY order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.add_trade_action("PYRAMID_BUY", ticker, add_shares, close_price, reason)
                                else:
                                    self.add_log(f"❌ [{ticker}] PYRAMID_BUY order failed. Reason: {order_res.get('error')}")

                            elif action == "PARTIAL_SELL" and current_shares > 0:
                                sell_qty = max(1, int(current_shares * 0.40))
                                pnl = (close_price - avg_cost) * sell_qty
                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-TP"
                                self.pending_exit_tickers.add(ticker)
                                self.add_log(f"🟢 [{ticker}] PARTIAL_SELL (TP1 分批止盈 40%) signal triggered! Market selling {sell_qty} shares (Est. PnL ${pnl:.2f})...")
                                order_res = self.adapter.submit_market_order(ticker, sell_qty, "sell", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.add_log(f"✅ [{ticker}] PARTIAL_SELL order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.add_trade_action("PARTIAL_SELL", ticker, sell_qty, close_price, reason, pnl=pnl)
                                else:
                                    self.pending_exit_tickers.discard(ticker)
                                    self.add_log(f"❌ [{ticker}] PARTIAL_SELL order failed. Reason: {order_res.get('error')}")

                            elif action == "PARTIAL_COVER" and current_shares < 0:
                                cover_qty = max(1, int(abs(current_shares) * 0.40))
                                pnl = (avg_cost - close_price) * cover_qty
                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-TP"
                                self.pending_exit_tickers.add(ticker)
                                self.add_log(f"🟢 [{ticker}] PARTIAL_COVER (TP1 分批止回补 40%) signal triggered! Market buying {cover_qty} shares (Est. PnL ${pnl:.2f})...")
                                order_res = self.adapter.submit_market_order(ticker, cover_qty, "buy", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.add_log(f"✅ [{ticker}] PARTIAL_COVER order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.add_trade_action("PARTIAL_COVER", ticker, cover_qty, close_price, reason, pnl=pnl)
                                else:
                                    self.pending_exit_tickers.discard(ticker)
                                    self.add_log(f"❌ [{ticker}] PARTIAL_COVER order failed. Reason: {order_res.get('error')}")

                            elif action == "SHORT" and current_shares == 0:
                                account = self.adapter.get_account_summary()
                                total_equity = account['equity']
                                
                                risk_pct = self.strategy_params.get("risk_per_trade_pct", 0.0030)
                                max_pct = self.strategy_params.get("max_position_size_pct", 0.12)
                                stop_min_pct = self.strategy_params.get("stop_min_pct", 0.0025)
                                stop_max_pct = self.strategy_params.get("stop_max_pct", 0.0060)
                                initial_stop_atr_mult = self.strategy_params.get("initial_stop_atr_mult", 1.05)

                                atr_val = float(row['ATR']) if 'ATR' in row and row['ATR'] > 0 else close_price * 0.004
                                atr_pct = (atr_val / close_price) if close_price > 0 else 0.004
                                stop_dist_pct = min(stop_max_pct, max(stop_min_pct, initial_stop_atr_mult * atr_pct))
                                stop_distance = close_price * stop_dist_pct

                                dollar_risk = total_equity * risk_pct
                                base_shares = int(dollar_risk / stop_distance) if stop_distance > 0 else int((total_equity * max_pct) / close_price)
                                max_shares = int((total_equity * max_pct) / close_price)
                                shares = max(1, min(base_shares, max_shares))

                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-ENTRY"
                                self.pending_entry_tickers.add(ticker)
                                self.entry_times[ticker] = datetime.datetime.now()

                                self.add_log(f"📉 [{ticker}] SHORT signal triggered! Market shorting {shares} shares...")
                                order_res = self.adapter.submit_market_order(ticker, shares, "sell", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.add_log(f"✅ [{ticker}] SHORT order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.add_trade_action("SHORT", ticker, shares, close_price, reason)
                                else:
                                    self.pending_entry_tickers.discard(ticker)
                                    self.add_log(f"❌ [{ticker}] SHORT order failed. Reason: {order_res.get('error')}")

                            elif action == "SELL" and current_shares > 0:
                                pnl = (close_price - avg_cost) * current_shares
                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-EXIT"
                                self.pending_exit_tickers.add(ticker)
                                self.add_log(f"🔔 [{ticker}] SELL signal triggered! Market selling {current_shares} shares (Est. PnL ${pnl:.2f})...")
                                order_res = self.adapter.submit_market_order(ticker, current_shares, "sell", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.add_log(f"✅ [{ticker}] SELL order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.add_trade_action("SELL", ticker, current_shares, close_price, reason, pnl=pnl)
                                    if ticker in self.highest_prices:
                                        del self.highest_prices[ticker]
                                else:
                                    self.pending_exit_tickers.discard(ticker)
                                    self.add_log(f"❌ [{ticker}] SELL order failed. Reason: {order_res.get('error')}")

                            elif action == "COVER" and current_shares < 0:
                                cover_qty = abs(current_shares)
                                pnl = (avg_cost - close_price) * cover_qty
                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-EXIT"
                                self.pending_exit_tickers.add(ticker)
                                self.add_log(f"🔔 [{ticker}] COVER signal triggered! Market buying {cover_qty} shares (Est. PnL ${pnl:.2f})...")
                                order_res = self.adapter.submit_market_order(ticker, cover_qty, "buy", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.add_log(f"✅ [{ticker}] COVER order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.add_trade_action("COVER", ticker, cover_qty, close_price, reason, pnl=pnl)
                                else:
                                    self.pending_exit_tickers.discard(ticker)
                                    self.add_log(f"❌ [{ticker}] COVER order failed. Reason: {order_res.get('error')}")
                                    
                        except Exception as ex:
                            self.add_log(f"⚠️ Error scanning {ticker}: {str(ex)}")

                loop_delay = 5 if is_market_opening_window else 30
                await asyncio.sleep(loop_delay)

            except asyncio.CancelledError:
                self.add_log("Background trading loop task cancelled.")
                break
            except Exception as e:
                self.add_log(f"⚠️ Main loop exception: {str(e)}")
                await asyncio.sleep(30)
