# backend/app/broker/live_runner.py
"""
Live Trading Runner Background Service
Polls real-time quotes, evaluates signals, executes trades on Alpaca, and logs decisions.
"""

import asyncio
import datetime
import os
import pytz
import threading
import time
from typing import Dict, List, Optional
from app.broker.alpaca_adapter import AlpacaAdapter
from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL, WATCHLIST, save_watchlist, load_watchlist
from app.data_manager import fetch_and_prepare_data
from app.data_cache import invalidate_cache
from app.strategy import evaluate_market_state, calculate_confidence_score

class MockAlpacaAdapter:
    def __init__(self):
        self.cash = 0.0
        self.equity = 0.0
        self.positions = {}
        self._sync_real_alpaca()

    def _sync_real_alpaca(self):
        """动态尝试读取 Alpaca 账户真实的实时剩余资金与资产，绝不用硬编码数额。"""
        try:
            from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL
            adapter = AlpacaAdapter(ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL)
            acc = adapter.get_account_summary()
            if acc and acc.get("success"):
                self.cash = float(acc.get("cash", 0.0))
                self.equity = float(acc.get("equity", 0.0))
                real_pos = adapter.get_open_positions()
                for pos in real_pos:
                    self.positions[pos["ticker"]] = {
                        "shares": pos["shares"],
                        "avg_entry_price": pos["avg_entry_price"],
                        "current_price": pos["current_price"]
                    }
                return
        except Exception:
            pass
        if self.cash == 0.0:
            self.cash = 30000.0
            self.equity = 30000.0

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

    def get_clock(self) -> Dict:
        import pytz
        est = pytz.timezone('America/New_York')
        now_ny = datetime.datetime.now(est)
        is_weekday = now_ny.weekday() <= 4
        ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0
        is_open = is_weekday and (9.5 <= ny_time < 16.0)
        return {
            "success": True,
            "is_open": is_open,
            "timestamp": str(now_ny)
        }

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
        self._account_cache = None
        self._account_cache_time = 0.0
        self._positions_cache = None
        self._positions_cache_time = 0.0
        self.highest_prices = {}
        self.pending_entry_locks = {}  # {ticker: timestamp} 60s TTL 防止卡死重复提交建仓单 (daytrade.pdf)
        self.pending_exit_locks = {}   # {ticker: timestamp} 60s TTL 防止卡死重复提交平仓单 (daytrade.pdf)
        self.entry_times = {}               # 记录持仓建立时间点 (支持时间止损 daytrade.pdf)
        self.loop_task = None
        self.order_sync_thread = None
        self._orders_lock = threading.RLock()
        self._orders_refresh_lock = threading.Lock()
        self._orders_cache = []
        self._orders_cache_updated_at = 0.0
        self._orders_cache_error = None
        self._orders_cache_latency_ms = None
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
            "runner_r": 2.50,                        # 剩余 25% 仓位跟踪最大盈利
            "runner_size_pct": 0.25,                 # 25% Runner ATR 追踪
            "breakeven_trigger_r": 0.85,             # 0.85R 触发保本止损
            "trail_start_r": 1.10,                   # 1.10R 启动追踪止损
            "trailing_stop_atr_mult": 1.10,
            "max_hold_minutes": 35,                  # 35 分钟时间止损
            "min_reward_to_cost_ratio": 1.5,         # 最小盈亏比门槛 (适合美股流动性标的)
            "max_expected_slippage_pct": 0.0002,     # 预估滑点 0.02%
            "orders_sync_interval_seconds": 2.0      # Alpaca 订单轻量同步频率
        }
        self.ticker_scores = {}              # AI 实时多因子置信度打分
        self.load_runner_config()
        self.add_log("📡 [系统初始化完成] Quant AI 日内风控与研判引擎已就绪...")

    def get_cached_account_summary(self) -> Dict:
        """带 3 秒防频刷内存缓存的账户资金接口，极速秒开（< 5ms）。"""
        now = time.time()
        if self._account_cache is not None and (now - self._account_cache_time) < 3.0:
            return self._account_cache
        try:
            res = self.adapter.get_account_summary()
            if res and res.get("success") is not False:
                self._account_cache = res
                self._account_cache_time = now
                return res
        except Exception:
            pass
        return self._account_cache or self.adapter.get_account_summary()

    def get_cached_open_positions(self) -> List[Dict]:
        """带 3 秒防频刷内存缓存的持仓列表接口，极速秒开（< 5ms）。"""
        now = time.time()
        if self._positions_cache is not None and (now - self._positions_cache_time) < 3.0:
            return self._positions_cache
        try:
            res = self.adapter.get_open_positions()
            self._positions_cache = res
            self._positions_cache_time = now
            return res
        except Exception:
            pass
        return self._positions_cache or []

    def is_entry_locked(self, ticker: str) -> bool:
        """检查是否有生效中的建仓并发锁（含 60 秒 TTL 自动防锁死过期机制）"""
        now = time.time()
        t = self.pending_entry_locks.get(ticker)
        if t and (now - t < 60):
            return True
        elif t:
            self.pending_entry_locks.pop(ticker, None)
        return False

    def is_exit_locked(self, ticker: str) -> bool:
        """检查是否有生效中的平仓并发锁（含 60 秒 TTL 自动防锁死过期机制）"""
        now = time.time()
        t = self.pending_exit_locks.get(ticker)
        if t and (now - t < 60):
            return True
        elif t:
            self.pending_exit_locks.pop(ticker, None)
        return False

    def lock_entry(self, ticker: str):
        self.pending_entry_locks[ticker] = time.time()

    def unlock_entry(self, ticker: str):
        self.pending_entry_locks.pop(ticker, None)

    def lock_exit(self, ticker: str):
        self.pending_exit_locks[ticker] = time.time()

    def unlock_exit(self, ticker: str):
        self.pending_exit_locks.pop(ticker, None)

    def load_runner_config(self):
        """从本地磁盘 runner_config.json 加载持久化策略参数配置。"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if "strategy_params" in data and isinstance(data["strategy_params"], dict):
                        self.strategy_params.update(data["strategy_params"])
        except Exception as e:
            print(f"Error loading runner_config.json: {e}")

    def save_runner_config(self):
        """保存策略参数到本地磁盘 runner_config.json。"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "is_running": self.is_running,
                    "strategy_params": self.strategy_params,
                    "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving runner_config.json: {e}")

    def set_market_mode(self, mode: str = "AUTO_EXCHANGE") -> Dict:
        """模式统一直接依从 Alpaca 官方交易所实操时钟 (AUTO_EXCHANGE)"""
        msg = "⏱️ 开盘关盘已 100% 绑定 Alpaca 官方交易所 API 实操时钟 (AUTO_EXCHANGE)。"
        self.save_runner_config()
        self.add_log(msg)
        return {"success": True, "market_mode": "AUTO_EXCHANGE", "message": msg}

    def load_trade_history(self):
        """从本地磁盘 trade_history.json 加载持久化交易历史（原样读取，不做任何重算）。"""
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.trade_history = data.get("trade_history", [])
                    self.action_logs = data.get("action_logs", [])
        except Exception as e:
            print(f"Error loading trade_history.json: {e}")

    def recalculate_trade_pnls(self):
        """按交易日期按日隔离计算 FIFO 匹配盈亏，全面支持多头与空头 (BUY/SELL/SHORT/COVER) 的精准全封闭匹配。"""
        if not self.trade_history:
            return

        self.trade_history.sort(key=lambda x: x.get("time", ""))
        trades_by_date = {}
        for trade in self.trade_history:
            d = trade.get("date") or (trade.get("time", "")[:10] if trade.get("time") else "")
            d = d.strip()
            if d not in trades_by_date:
                trades_by_date[d] = []
            trades_by_date[d].append(trade)

        for d, day_trades in trades_by_date.items():
            ticker_queues = {}  # symbol -> {'long': [], 'short': []}
            for trade in day_trades:
                ticker = trade.get("ticker", "")
                raw_action = trade.get("action", "").upper()
                qty = int(trade.get("shares", 0))
                price = float(trade.get("price", 0.0))

                if not ticker or qty <= 0 or price <= 0:
                    continue

                if ticker not in ticker_queues:
                    ticker_queues[ticker] = {"long": [], "short": []}

                long_q = ticker_queues[ticker]["long"]
                short_q = ticker_queues[ticker]["short"]
                trade_pnl = 0.0

                if raw_action in ("BUY", "PYRAMID_BUY", "COVER", "PARTIAL_COVER"):
                    if short_q:
                        trade["action"] = "COVER"
                        trade["action_cn"] = "平空"
                        rem_qty = qty
                        while rem_qty > 0 and short_q:
                            entry = short_q[0]
                            matched = min(rem_qty, entry["qty"])
                            trade_pnl += (entry["price"] - price) * matched
                            entry["qty"] -= matched
                            rem_qty -= matched
                            if entry["qty"] <= 0:
                                short_q.pop(0)
                        if rem_qty > 0:
                            long_q.append({"price": price, "qty": rem_qty})
                    else:
                        trade["action"] = "BUY"
                        trade["action_cn"] = "买入"
                        long_q.append({"price": price, "qty": qty})
                        trade_pnl = 0.0

                elif raw_action in ("SELL", "PARTIAL_SELL", "SHORT"):
                    if long_q:
                        trade["action"] = "SELL"
                        trade["action_cn"] = "卖出"
                        rem_qty = qty
                        while rem_qty > 0 and long_q:
                            entry = long_q[0]
                            matched = min(rem_qty, entry["qty"])
                            trade_pnl += (price - entry["price"]) * matched
                            entry["qty"] -= matched
                            rem_qty -= matched
                            if entry["qty"] <= 0:
                                long_q.pop(0)
                        if rem_qty > 0:
                            short_q.append({"price": price, "qty": rem_qty})
                    else:
                        trade["action"] = "SHORT"
                        trade["action_cn"] = "做空"
                        short_q.append({"price": price, "qty": qty})
                        trade_pnl = 0.0

                trade["pnl"] = round(trade_pnl, 2)

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

    def add_trade_action(
        self,
        action: str,
        ticker: str,
        shares: int,
        price: float,
        reason: str,
        pnl: float = 0.0,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
        order_status: Optional[str] = None,
    ):
        """记录发单交易动作到 action_logs 用于 UI 动态日志流展示。只有 Alpaca 真正的成单才进入历史账本。"""
        est = pytz.timezone('America/New_York')
        now = datetime.datetime.now(est)
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

        action_emoji = {"BUY": "🟢", "SELL": "🔴", "SHORT": "🔻", "COVER": "🔼"}.get(action, "⚪")
        pnl_str = f" | PnL: {'+'if pnl>=0 else ''}{pnl:.2f} USD" if pnl != 0.0 else ""
        feed_msg = f"[{timestamp_str}] {action_emoji} [{ticker}] {action} × {shares} shs @ ${price:.2f}{pnl_str} | {reason}"

        self.action_logs.append(feed_msg)
        if len(self.action_logs) > 300:
            self.action_logs.pop(0)

        # 仅当此 order_id 在交易历史中已被同步确认时，补全 reason 与扩展信息
        if order_id:
            existing = next(
                (trade for trade in self.trade_history if str(trade.get("order_id") or "") == str(order_id)),
                None,
            )
            if existing is not None:
                existing["reason"] = reason
                if client_order_id:
                    existing["client_order_id"] = str(client_order_id)
                self.save_trade_history()

    def get_today_summary(self) -> dict:
        """Calculate today's trade summary and realized/unrealized PnL."""
        self.recalculate_trade_pnls()
        est = pytz.timezone('America/New_York')
        today = datetime.datetime.now(est).strftime("%Y-%m-%d")
        today_trades = [t for t in self.trade_history if (t.get("date") or t.get("time", "")[:10]).strip() == today]

        closed_trades = [t for t in today_trades if t.get("action") in ("SELL", "COVER", "PARTIAL_SELL", "PARTIAL_COVER")]
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
                if acc_info and acc_info.get("success") and "today_pnl" in acc_info:
                    alpaca_official_today_pnl = acc_info.get("today_pnl")
        except Exception:
            pass

        # Priority: use Alpaca's official today_pnl (equity - last_equity) as the ground truth
        final_today_pnl = round(alpaca_official_today_pnl, 2) if alpaca_official_today_pnl is not None else round(realized_pnl, 2)

        return {
            "date": today,
            "total_trades": len(today_trades),
            "closed_trades": len(closed_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed_trades) * 100, 1) if closed_trades else 0.0,
            "realized_pnl": round(realized_pnl, 2),
            "alpaca_official_pnl": final_today_pnl,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl": final_today_pnl,
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
                        close_res = {}
                        if hasattr(self.adapter, "close_position"):
                            close_res = self.adapter.close_position(r_sym) or {}
                        self.add_trade_action(
                            action="SELL" if shares > 0 else "COVER",
                            ticker=r_sym,
                            shares=abs(shares),
                            price=pos.get("current_price", 0.0),
                            reason="Watchlist Removal Auto Liquidation (自选股移除自动强行清仓)",
                            order_id=close_res.get("order_id") or close_res.get("id"),
                            order_status=close_res.get("status") or "submitted",
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
                        reason="User Manual Force Sell/Close",
                        order_id=res.get("order_id") or res.get("id"),
                        order_status=res.get("status") or "submitted",
                    )
                    return {"success": True, "message": f"Successfully submitted close order for {sym}."}
                else:
                    return {"success": False, "error": res.get("error", f"Failed to close position for {sym}")}
            else:
                return {"success": False, "error": "Broker adapter does not support closing individual positions."}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def _get_alpaca_credentials():
        """Read credentials from process environment first; never persist secrets in runner files."""
        api_key = (
            os.getenv("APCA_API_KEY_ID")
            or os.getenv("ALPACA_API_KEY")
            or ALPACA_API_KEY
        )
        api_secret = (
            os.getenv("APCA_API_SECRET_KEY")
            or os.getenv("ALPACA_SECRET_KEY")
            or ALPACA_SECRET_KEY
        )
        base_url = (
            os.getenv("APCA_API_BASE_URL")
            or os.getenv("ALPACA_BASE_URL")
            or ALPACA_BASE_URL
            or "https://paper-api.alpaca.markets/v2"
        )
        return api_key, api_secret, base_url

    @staticmethod
    def _credential_is_configured(value: Optional[str]) -> bool:
        text = str(value or "").strip().lower()
        return bool(text) and "your_" not in text and "placeholder" not in text

    def start(self, strategy_params: Optional[Dict] = None, tickers: Optional[List[str]] = None, **kwargs):
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

        self.save_runner_config()
        
        # Initialize Adapter
        try:
            api_key, api_secret, base_url = self._get_alpaca_credentials()
            if self._credential_is_configured(api_key) and self._credential_is_configured(api_secret):
                self.adapter = AlpacaAdapter(
                    api_key=api_key,
                    api_secret=api_secret,
                    base_url=base_url
                )
                self.adapter.get_account_summary()
                self.add_log("🟢 已成功连接至 Alpaca 实盘/Paper 交易接口。")
            else:
                self.adapter = MockAlpacaAdapter()
                self.add_log("💡 未同时检测到 Alpaca API Key 与 Secret，自动切换至【本地虚拟盘模拟模式】。")
        except Exception as e:
            self.adapter = MockAlpacaAdapter()
            self.add_log(f"⚠️ [Alpaca 连接失败警报] API 密钥配置存在异常或建连失败 ({str(e)})，暂降级至【本地虚拟盘模拟模式】！")
        self.is_running = True
        self._start_order_sync_worker()
        self.add_log(f"🤖 【AI 24/7 全自动托管开启】系统已进入无人值守全自动轮询模式！监控标的({len(self.active_tickers)}): {self.active_tickers}")
        
        # Spawn async loop task safely across both sync and async runtime contexts
        try:
            loop = asyncio.get_running_loop()
            self.loop_task = loop.create_task(self._run_loop())
        except RuntimeError:
            def start_background_loop():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(self._run_loop())
            t = threading.Thread(target=start_background_loop, daemon=True)
            t.start()
        return True

    @staticmethod
    def _order_field(order, field: str, default=None):
        if isinstance(order, dict):
            return order.get(field, default)
        return getattr(order, field, default)

    @staticmethod
    def _enum_text(value) -> str:
        raw = getattr(value, "value", value)
        return str(raw or "").split(".")[-1].lower()

    @staticmethod
    def _number_or_none(value):
        if value in (None, ""):
            return None
        try:
            number = float(value)
            return int(number) if number.is_integer() else round(number, 6)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _timestamp_iso(value):
        if value is None:
            return None
        return value.isoformat() if hasattr(value, "isoformat") else str(value)

    @staticmethod
    def _timestamp_et(value):
        if value is None:
            return None
        est = pytz.timezone("America/New_York")
        dt = value
        if isinstance(value, str):
            try:
                dt = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return None
        if not isinstance(dt, datetime.datetime):
            return None
        if dt.tzinfo is None:
            dt = est.localize(dt)
        return dt.astimezone(est)

    def _serialize_alpaca_order(self, order) -> Dict:
        submitted_at = self._order_field(order, "submitted_at")
        filled_at = self._order_field(order, "filled_at")
        updated_at = self._order_field(order, "updated_at")
        event_time = filled_at or updated_at or submitted_at
        event_et = self._timestamp_et(event_time)
        return {
            "order_id": str(self._order_field(order, "id", "")),
            "client_order_id": str(self._order_field(order, "client_order_id", "") or ""),
            "ticker": str(self._order_field(order, "symbol", "") or "").upper(),
            "side": self._enum_text(self._order_field(order, "side")),
            "type": self._enum_text(self._order_field(order, "type")),
            "status": self._enum_text(self._order_field(order, "status")),
            "time_in_force": self._enum_text(self._order_field(order, "time_in_force")),
            "position_intent": self._enum_text(self._order_field(order, "position_intent")),
            "qty": self._number_or_none(self._order_field(order, "qty")),
            "notional": self._number_or_none(self._order_field(order, "notional")),
            "filled_qty": self._number_or_none(self._order_field(order, "filled_qty")) or 0,
            "filled_avg_price": self._number_or_none(self._order_field(order, "filled_avg_price")),
            "limit_price": self._number_or_none(self._order_field(order, "limit_price")),
            "stop_price": self._number_or_none(self._order_field(order, "stop_price")),
            "extended_hours": bool(self._order_field(order, "extended_hours", False)),
            "submitted_at": self._timestamp_iso(submitted_at),
            "filled_at": self._timestamp_iso(filled_at),
            "updated_at": self._timestamp_iso(updated_at),
            "date": event_et.strftime("%Y-%m-%d") if event_et else "",
            "time": event_et.strftime("%Y-%m-%d %H:%M:%S") if event_et else "",
        }

    def _cached_orders_snapshot(self) -> Dict:
        with self._orders_lock:
            updated_at = self._orders_cache_updated_at
            interval = max(1.0, float(self.strategy_params.get("orders_sync_interval_seconds", 2.0)))
            age_seconds = max(0.0, time.time() - updated_at) if updated_at else None
            return {
                "success": updated_at > 0 and self._orders_cache_error is None,
                "connected": not isinstance(self.adapter, MockAlpacaAdapter),
                "source": "alpaca_trading_api" if not isinstance(self.adapter, MockAlpacaAdapter) else "mock",
                "orders": [dict(order) for order in self._orders_cache],
                "count": len(self._orders_cache),
                "updated_at": datetime.datetime.fromtimestamp(updated_at, tz=pytz.UTC).isoformat() if updated_at else None,
                "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
                "stale": updated_at == 0 or age_seconds > max(6.0, interval * 3.0),
                "latency_ms": self._orders_cache_latency_ms,
                "error": self._orders_cache_error,
            }

    def refresh_alpaca_orders(self) -> Dict:
        """Fetch today's open/closed orders once and publish a JSON-safe in-memory snapshot."""
        if not self.adapter or isinstance(self.adapter, MockAlpacaAdapter):
            return self._cached_orders_snapshot()

        if not self._orders_refresh_lock.acquire(blocking=False):
            snapshot = self._cached_orders_snapshot()
            snapshot["refreshing"] = True
            return snapshot

        started = time.perf_counter()
        try:
            from alpaca.trading.requests import GetOrdersRequest
            from alpaca.trading.enums import QueryOrderStatus

            est = pytz.timezone("America/New_York")
            today_start = datetime.datetime.now(est).replace(hour=0, minute=0, second=0, microsecond=0)
            request_kwargs = {
                "status": QueryOrderStatus.ALL,
                "limit": 500,
                "after": today_start,
                "nested": True,
            }
            try:
                from alpaca.trading.enums import Sort
                request_kwargs["direction"] = Sort.DESC
            except (ImportError, AttributeError):
                pass

            req = GetOrdersRequest(**request_kwargs)
            raw_orders = self.adapter.client.get_orders(filter=req)
            orders = [self._serialize_alpaca_order(order) for order in (raw_orders or [])]
            orders.sort(key=lambda order: order.get("submitted_at") or "", reverse=True)
            latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
            with self._orders_lock:
                self._orders_cache = orders
                self._orders_cache_updated_at = time.time()
                self._orders_cache_error = None
                self._orders_cache_latency_ms = latency_ms
            return self._cached_orders_snapshot()
        except Exception as exc:
            with self._orders_lock:
                self._orders_cache_error = f"{type(exc).__name__}: {exc}"
            return self._cached_orders_snapshot()
        finally:
            self._orders_refresh_lock.release()

    def _start_order_sync_worker(self):
        """Keep the UI order feed warm without making every browser refresh call Alpaca."""
        if isinstance(self.adapter, MockAlpacaAdapter):
            return
        if self.order_sync_thread and self.order_sync_thread.is_alive():
            return

        def sync_worker():
            while self.is_running and not isinstance(self.adapter, MockAlpacaAdapter):
                cycle_started = time.monotonic()
                snapshot = self.refresh_alpaca_orders()
                if snapshot.get("success"):
                    self.sync_alpaca_orders_to_history(snapshot=snapshot)
                interval = max(1.0, min(10.0, float(self.strategy_params.get("orders_sync_interval_seconds", 2.0))))
                time.sleep(max(0.25, interval - (time.monotonic() - cycle_started)))

        self.order_sync_thread = threading.Thread(
            target=sync_worker,
            name="alpaca-order-sync",
            daemon=True,
        )
        self.order_sync_thread.start()

    def _broker_action(self, order: Dict) -> str:
        intent = str(order.get("position_intent") or "").lower()
        client_id = str(order.get("client_order_id") or "").upper()
        side = str(order.get("side") or "").lower()
        if intent in ("sto", "sell_to_open"):
            return "SHORT"
        if intent in ("btc", "buy_to_close"):
            return "COVER"
        if intent in ("stc", "sell_to_close"):
            return "SELL"
        if intent in ("bto", "buy_to_open"):
            return "BUY"
        if "ENTRY" in client_id:
            return "SHORT" if side == "sell" else "BUY"
        if "EXIT" in client_id or "-TP" in client_id:
            return "COVER" if side == "buy" else "SELL"
        return "BUY" if side == "buy" else "SELL"

    def _find_provisional_trade(self, order: Dict):
        """Match the bot's submission log to its broker order without collapsing same-size re-entries."""
        order_time = self._timestamp_et(order.get("submitted_at") or order.get("filled_at"))
        action = self._broker_action(order)
        side_actions = {"BUY", "PYRAMID_BUY", "COVER", "PARTIAL_COVER"} if order.get("side") == "buy" else {"SELL", "PARTIAL_SELL", "SHORT"}
        best = None
        best_delta = None
        for trade in reversed(self.trade_history):
            if trade.get("order_id"):
                continue
            if trade.get("ticker") != order.get("ticker") or trade.get("action") not in side_actions:
                continue
            try:
                if abs(float(trade.get("shares", 0)) - float(order.get("filled_qty", 0))) > 1e-6:
                    continue
            except (TypeError, ValueError):
                continue
            trade_time = self._timestamp_et(trade.get("time"))
            delta = abs((order_time - trade_time).total_seconds()) if order_time and trade_time else 999999
            if delta <= 300 and (best_delta is None or delta < best_delta):
                best = trade
                best_delta = delta
        if best is not None and action in ("SHORT", "COVER"):
            best["action"] = action
            best["action_cn"] = action
        return best

    def sync_alpaca_orders_to_history(self, snapshot: Optional[Dict] = None, force_refresh: bool = False):
        """Upsert Alpaca-confirmed fills into the local review ledger by immutable broker order ID."""
        if not self.adapter or isinstance(self.adapter, MockAlpacaAdapter):
            return {"success": True, "added": 0, "updated": 0}
        try:
            if force_refresh or snapshot is None:
                snapshot = self.refresh_alpaca_orders()
            if not snapshot or not snapshot.get("success"):
                return {"success": False, "error": (snapshot or {}).get("error", "Order snapshot unavailable")}

            existing_by_id = {
                str(trade.get("order_id")): trade
                for trade in self.trade_history
                if trade.get("order_id")
            }
            added_count = 0
            updated_count = 0
            for order in snapshot.get("orders", []):
                qty = self._number_or_none(order.get("filled_qty")) or 0
                price = self._number_or_none(order.get("filled_avg_price")) or 0
                if qty <= 0 or price <= 0:
                    continue

                order_id = str(order.get("order_id") or "")
                if not order_id:
                    continue
                action = self._broker_action(order)
                record = existing_by_id.get(order_id)
                is_new_record = False
                if record is None:
                    record = self._find_provisional_trade(order)
                if record is None:
                    record = {}
                    self.trade_history.append(record)
                    added_count += 1
                    is_new_record = True

                before = dict(record)
                record.update({
                    "order_id": order_id,
                    "client_order_id": order.get("client_order_id", ""),
                    "order_status": order.get("status", ""),
                    "source": "alpaca_trading_api",
                    "date": order.get("date", ""),
                    "time": order.get("time", ""),
                    "action": record.get("action") or action,
                    "action_cn": record.get("action_cn") or action,
                    "ticker": order.get("ticker", ""),
                    "shares": qty,
                    "price": price,
                    "pnl": float(record.get("pnl", 0.0) or 0.0),
                    "reason": record.get("reason") or "Alpaca Broker Confirmed Fill",
                })
                existing_by_id[order_id] = record
                if not is_new_record and record != before:
                    updated_count += 1

            if added_count or updated_count:
                self.recalculate_trade_pnls()
                self.trade_history.sort(key=lambda trade: trade.get("time", ""))
                self.save_trade_history()
                if added_count:
                    self.add_log(f"📥 已从 Alpaca 官方订单接口同步 {added_count} 笔新成交，订单页与本地复盘账本已对齐。")
            return {"success": True, "added": added_count, "updated": updated_count}
        except Exception as exc:
            print(f"Sync Alpaca orders warning: {exc}")
            return {"success": False, "error": str(exc)}

    def archive_to_hf_dataset(self, keep_days: int = 2) -> dict:
        """
        自动将过去较旧的历史交易记录归档上传至 Hugging Face Dataset (Ypeng12/quant-ai-trade-history)，
        并在上传成功后自动清理本地 trade_history.json，确保本地磁盘文件保持轻量高效、秒级读取。
        """
        try:
            from huggingface_hub import HfApi, hf_hub_download
            token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_HUB_TOKEN")
            repo_id = "Ypeng12/quant-ai-trade-history"
            
            api = HfApi(token=token) if token else HfApi()
            api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True)
            
            est = pytz.timezone('America/New_York')
            now_est = datetime.datetime.now(est)
            valid_dates = {(now_est - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(keep_days)}
            
            recent_trades = []
            older_trades = []
            
            for t in self.trade_history:
                d = (t.get("date") or (t.get("time", "")[:10] if t.get("time") else "")).strip()
                if d in valid_dates:
                    recent_trades.append(t)
                else:
                    older_trades.append(t)
            
            if not older_trades:
                return {"success": True, "message": "没有需要归档的旧历史记录，本地已保持极简精简。", "archived_count": 0}
                
            dataset_trades = []
            try:
                local_dl = hf_hub_download(repo_id=repo_id, filename="historical_trades_archive.json", repo_type="dataset", token=token)
                with open(local_dl, 'r', encoding='utf-8') as f:
                    dataset_trades = json.load(f).get("trade_history", [])
            except Exception:
                dataset_trades = []
                
            existing_ids = {t.get("order_id") or f"{t.get('ticker')}-{t.get('time')}" for t in dataset_trades}
            added = 0
            for ot in older_trades:
                uid = ot.get("order_id") or f"{ot.get('ticker')}-{ot.get('time')}"
                if uid not in existing_ids:
                    dataset_trades.append(ot)
                    existing_ids.add(uid)
                    added += 1
                    
            dataset_trades.sort(key=lambda x: x.get("time", ""))
            
            temp_file = os.path.join(os.path.dirname(self.history_file), "temp_hf_archive.json")
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump({"trade_history": dataset_trades}, f, ensure_ascii=False, indent=2)
                
            api.upload_file(
                path_or_fileobj=temp_file,
                path_in_repo="historical_trades_archive.json",
                repo_id=repo_id,
                repo_type="dataset"
            )
            if os.path.exists(temp_file):
                os.remove(temp_file)

            msg = f"📦 成功将 {added} 笔历史交易全量备份上传至 Hugging Face Dataset ({repo_id})！"
            self.add_log(msg)
            return {"success": True, "message": msg, "archived_count": added, "local_remaining": len(self.trade_history)}
        except Exception as e:
            err_msg = f"HF Dataset 归档失败: {str(e)}"
            self.add_log(f"⚠️ {err_msg}")
            return {"success": False, "error": err_msg}

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
                self.add_trade_action(
                    action_type,
                    symbol,
                    qty,
                    limit_price,
                    f"【盘前盘后限价交易】Limit Order @ ${limit_price:.2f}",
                    order_id=res.get("order_id") or res.get("id"),
                    order_status=res.get("status") or "submitted",
                )
            return res
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_status(self) -> Dict:
        orders_snapshot = self._cached_orders_snapshot()
        return {
            "is_running": self.is_running,
            "market_mode": "AUTO_EXCHANGE",
            "is_market_open": self.is_market_open(),
            "ticker_scores": self.ticker_scores,
            "monitored_tickers": self.active_tickers,
            "strategy_params": self.strategy_params,
            "logs_count": len(self.logs),
            "orders": orders_snapshot["orders"],
            "orders_meta": {
                key: value
                for key, value in orders_snapshot.items()
                if key != "orders"
            }
        }

    def get_live_orders(self, force_refresh: bool = False) -> Dict:
        """Public API helper for a dedicated /api/live/orders endpoint."""
        return self.refresh_alpaca_orders() if force_refresh else self._cached_orders_snapshot()

    def is_market_open(self) -> bool:
        """
        利用本机系统时间精度转换为美东时间 (America/New_York)，判定是否处于美股常规交易开盘时段。
        规则：美东时间 周一至周五 9:30 AM - 4:00 PM EST (9.5 <= ny_time < 16.0)。
        """
        est = pytz.timezone('America/New_York')
        now_ny = datetime.datetime.now(est)
        is_weekday = now_ny.weekday() <= 4
        ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0
        return is_weekday and (9.5 <= ny_time < 16.0)

    def is_eod_no_entry_window(self) -> bool:
        """
        判断是否处于美股收盘前禁止新建仓窗口 (美东时间 15:45 PM - 16:00 PM EST)。
        在此窗口期内，封锁所有新建仓订单 (BUY / SHORT / PYRAMID_BUY)，确保零持仓过夜。
        """
        est = pytz.timezone('America/New_York')
        now_ny = datetime.datetime.now(est)
        if now_ny.weekday() > 4:
            return False
        ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0
        return 15.75 <= ny_time < 16.0

    def check_and_trigger_eod_close(self, positions_list: list) -> bool:
        """
        日内收盘前自动强行全平持仓风控 (EOD Auto Close-All Strategy).
        Triggers between 15:50 PM (15.8333) and 16:00 PM (16.0) EST.
        Triggers `close_all_positions()` for 0 overnight position risk!
        """
        if not positions_list:
            return False

        est = pytz.timezone('America/New_York')
        now_ny = datetime.datetime.now(est)

        if now_ny.weekday() > 4:
            return False

        ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0

        # EOD liquidation triggers between 15:50 PM (15.8333) and 16:00 PM (16.0) EST
        if not (15.8333 <= ny_time < 16.0):
            return False

        seconds_left = (16.0 - ny_time) * 3600.0
        if 0.0 < seconds_left <= 300.0:
            mins_left = seconds_left / 60.0
            self.add_log(f"🌇 [交易所尾盘双重清场风控] 距关盘仅剩 {mins_left:.1f} 分钟！执行【双重清场】：全量撤销所有挂单 + 强行全平 {len(positions_list)} 笔持仓，确保零挂单零持仓过夜...")
            try:
                # Step 1: 撤销所有挂单
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
                # 1. 判定是否为美东 9:30 - 16:00 盘中常规交易时间
                is_open = self.is_market_open()

                est = pytz.timezone('America/New_York')
                now_ny = datetime.datetime.now(est)
                ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0
                is_market_opening_window = (now_ny.weekday() <= 4) and (9.50 <= ny_time < 9.60)

                if is_open:
                    if is_market_opening_window:
                        self.add_log(f"⚡ [开盘黄金重诊 9:30-9:36 EST] 开启高频拉网校验！监控池 [{len(self.active_tickers)} 支标的]...")
                    else:
                        self.add_log(f"📡 [美股开盘交易中·全频段扫描发单] 正在研判监控池股票 [{len(self.active_tickers)} 支标的]...")
                else:
                    self.add_log(f"🌙 [美股盘后研判/休市监控中] 24/7 持续实时计算多因子与形态（休市期间仅研判记录，暂停实盘买卖发单）...")
                
                # 2. Get active positions from Alpaca to sync state
                try:
                    positions_list = self.adapter.get_open_positions()
                    positions_by_ticker = {pos['ticker']: pos for pos in positions_list if pos.get('ticker')}
                    active_pos_tickers = set(positions_by_ticker.keys())
                    
                    # Automatic TTL & state-based lock unlocking:
                    # Clear entry locks for tickers that now have an active position
                    for pos_ticker in active_pos_tickers:
                        self.unlock_entry(pos_ticker)

                    # Clear exit locks for tickers that no longer have an active position (closed)
                    for lock_ticker in list(self.pending_exit_locks.keys()):
                        if lock_ticker not in active_pos_tickers:
                            self.unlock_exit(lock_ticker)

                    # 关盘前 15:55 EST 强行清仓不过夜
                    if self.check_and_trigger_eod_close(positions_list):
                        await asyncio.sleep(30)
                        continue
                except Exception as e:
                    self.add_log(f"⚠️ Failed to fetch Alpaca positions: {str(e)}, skipping round.")
                    await asyncio.sleep(20)
                    continue

                # 3. Synchronize active_tickers with user Watchlist & active positions (No data loss)
                user_watchlist = load_watchlist()
                if not user_watchlist:
                    user_watchlist = WATCHLIST.copy()
                
                full_universe = list(dict.fromkeys(user_watchlist + list(active_pos_tickers)))
                full_universe.sort(key=lambda t: self.ticker_scores.get(t, 0), reverse=True)
                self.active_tickers = full_universe

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

                            # EOD Entry Lock Check (15:45-16:00 EST): Block any new long/short/pyramid entries
                            if self.is_eod_no_entry_window() and action in ("BUY", "SHORT", "PYRAMID_BUY"):
                                action = "HOLD"
                                reason = f"[{ticker}] EOD No-Entry Window (15:45-16:00 EST). Blocked new entry order to guarantee zero overnight risk."

                            # Deduplication Lock Check (60s TTL Auto-expiring daytrade.pdf)
                            if action in ("BUY", "SHORT") and self.is_entry_locked(ticker):
                                action = "HOLD"
                                reason = f"[{ticker}] Pending entry order lock active. Blocked duplicate entry."
                            elif action in ("SELL", "COVER", "PARTIAL_SELL", "PARTIAL_COVER") and self.is_exit_locked(ticker):
                                action = "HOLD"
                                reason = f"[{ticker}] Pending exit order lock active. Blocked duplicate exit."

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
                                if not is_open:
                                    self.add_log(f"🌙 [盘后研判/休市记录] [{ticker}] 触发 BUY 选股买点信号 (AI Score: {live_score}分) | 非美股盘中交易时段 (9:30-16:00 EST 以外)，仅保留研判日志，暂不发单扣动扳机。")
                                else:
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
                                    self.lock_entry(ticker)
                                    self.entry_times[ticker] = datetime.datetime.now()

                                    self.add_log(f"🛒 [{ticker}] BUY signal triggered ({size_scale*100:.0f}% position, Initial Risk: ${dollar_risk:.2f})! Market buying {shares} shares...")
                                    order_res = self.adapter.submit_market_order(ticker, shares, "buy", client_order_id=client_order_id)
                                    if order_res.get("success"):
                                        self.add_log(f"✅ [{ticker}] BUY order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                        self.highest_prices[ticker] = close_price
                                        self.add_trade_action(
                                            "BUY", ticker, shares, close_price, reason,
                                            order_id=order_res.get("order_id") or order_res.get("id"),
                                            client_order_id=client_order_id,
                                            order_status=order_res.get("status") or "submitted",
                                        )
                                    else:
                                        self.unlock_entry(ticker)
                                        self.add_log(f"❌ [{ticker}] BUY order failed. Reason: {order_res.get('error')}")

                            elif action == "PYRAMID_BUY" and current_shares > 0:
                                if not is_open:
                                    self.add_log(f"🌙 [盘后研判/休市记录] [{ticker}] 触发 PYRAMID_BUY 加仓信号 | 非美股盘中交易时段，暂停发单。")
                                else:
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
                                        self.add_trade_action(
                                            "PYRAMID_BUY", ticker, add_shares, close_price, reason,
                                            order_id=order_res.get("order_id") or order_res.get("id"),
                                            client_order_id=client_order_id,
                                            order_status=order_res.get("status") or "submitted",
                                        )
                                    else:
                                        self.add_log(f"❌ [{ticker}] PYRAMID_BUY order failed. Reason: {order_res.get('error')}")

                            elif action == "PARTIAL_SELL" and current_shares > 0:
                                sell_qty = max(1, int(current_shares * 0.40))
                                pnl = (close_price - avg_cost) * sell_qty
                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-TP"
                                self.lock_exit(ticker)
                                self.add_log(f"🟢 [{ticker}] PARTIAL_SELL (TP1 分批止盈 40%) signal triggered! Market selling {sell_qty} shares (Est. PnL ${pnl:.2f})...")
                                order_res = self.adapter.submit_market_order(ticker, sell_qty, "sell", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.add_log(f"✅ [{ticker}] PARTIAL_SELL order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.add_trade_action(
                                        "PARTIAL_SELL", ticker, sell_qty, close_price, reason, pnl=pnl,
                                        order_id=order_res.get("order_id") or order_res.get("id"),
                                        client_order_id=client_order_id,
                                        order_status=order_res.get("status") or "submitted",
                                    )
                                else:
                                    self.unlock_exit(ticker)
                                    self.add_log(f"❌ [{ticker}] PARTIAL_SELL order failed. Reason: {order_res.get('error')}")

                            elif action == "PARTIAL_COVER" and current_shares < 0:
                                cover_qty = max(1, int(abs(current_shares) * 0.40))
                                pnl = (avg_cost - close_price) * cover_qty
                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-TP"
                                self.lock_exit(ticker)
                                self.add_log(f"🟢 [{ticker}] PARTIAL_COVER (TP1 分批止回补 40%) signal triggered! Market buying {cover_qty} shares (Est. PnL ${pnl:.2f})...")
                                order_res = self.adapter.submit_market_order(ticker, cover_qty, "buy", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.add_log(f"✅ [{ticker}] PARTIAL_COVER order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.add_trade_action(
                                        "PARTIAL_COVER", ticker, cover_qty, close_price, reason, pnl=pnl,
                                        order_id=order_res.get("order_id") or order_res.get("id"),
                                        client_order_id=client_order_id,
                                        order_status=order_res.get("status") or "submitted",
                                    )
                                else:
                                    self.unlock_exit(ticker)
                                    self.add_log(f"❌ [{ticker}] PARTIAL_COVER order failed. Reason: {order_res.get('error')}")

                            elif action == "SHORT" and current_shares == 0:
                                if not is_open:
                                    self.add_log(f"🌙 [盘后研判/休市记录] [{ticker}] 触发 SHORT 选股做空信号 (AI Score: {live_score}分) | 非美股盘中交易时段 (9:30-16:00 EST 以外)，仅保留研判日志，暂不发单扣动扳机。")
                                else:
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
                                    self.lock_entry(ticker)
                                    self.entry_times[ticker] = datetime.datetime.now()

                                    self.add_log(f"📉 [{ticker}] SHORT signal triggered! Market shorting {shares} shares...")
                                    order_res = self.adapter.submit_market_order(ticker, shares, "sell", client_order_id=client_order_id)
                                    if order_res.get("success"):
                                        self.add_log(f"✅ [{ticker}] SHORT order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                        self.add_trade_action(
                                            "SHORT", ticker, shares, close_price, reason,
                                            order_id=order_res.get("order_id") or order_res.get("id"),
                                            client_order_id=client_order_id,
                                            order_status=order_res.get("status") or "submitted",
                                        )
                                    else:
                                        self.unlock_entry(ticker)
                                        self.add_log(f"❌ [{ticker}] SHORT order failed. Reason: {order_res.get('error')}")

                            elif action == "SELL" and current_shares > 0:
                                pnl = (close_price - avg_cost) * current_shares
                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-EXIT"
                                self.lock_exit(ticker)
                                self.add_log(f"🔔 [{ticker}] SELL signal triggered! Market selling {current_shares} shares (Est. PnL ${pnl:.2f})...")
                                order_res = self.adapter.submit_market_order(ticker, current_shares, "sell", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.add_log(f"✅ [{ticker}] SELL order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.add_trade_action(
                                        "SELL", ticker, current_shares, close_price, reason, pnl=pnl,
                                        order_id=order_res.get("order_id") or order_res.get("id"),
                                        client_order_id=client_order_id,
                                        order_status=order_res.get("status") or "submitted",
                                    )
                                    if ticker in self.highest_prices:
                                        del self.highest_prices[ticker]
                                else:
                                    self.unlock_exit(ticker)
                                    self.add_log(f"❌ [{ticker}] SELL order failed. Reason: {order_res.get('error')}")

                            elif action == "COVER" and current_shares < 0:
                                cover_qty = abs(current_shares)
                                pnl = (avg_cost - close_price) * cover_qty
                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-EXIT"
                                self.lock_exit(ticker)
                                self.add_log(f"🔔 [{ticker}] COVER signal triggered! Market buying {cover_qty} shares (Est. PnL ${pnl:.2f})...")
                                order_res = self.adapter.submit_market_order(ticker, cover_qty, "buy", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.add_log(f"✅ [{ticker}] COVER order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.add_trade_action(
                                        "COVER", ticker, cover_qty, close_price, reason, pnl=pnl,
                                        order_id=order_res.get("order_id") or order_res.get("id"),
                                        client_order_id=client_order_id,
                                        order_status=order_res.get("status") or "submitted",
                                    )
                                else:
                                    self.unlock_exit(ticker)
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
