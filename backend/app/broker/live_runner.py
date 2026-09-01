# backend/app/broker/live_runner.py
"""
Live Trading Runner Background Service (Modular Quant Core)
Polls real-time quotes, evaluates probabilistic signals, executes trades on Alpaca, and logs decisions.
"""

import asyncio
import datetime
import json
import math
import os
import pytz
import threading
import time
import uuid
from typing import Dict, List, Optional

from app.broker.alpaca_adapter import AlpacaAdapter
from app.broker.mock_adapter import MockAlpacaAdapter
from app.broker.universe_screener import UniverseScreener
from app.broker.risk_position_sizer import RiskPositionSizer
from app.broker.probability_engine import evaluate_mathematical_expectation
from app.alpha_engine import InstitutionalAlphaEngine
from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL, WATCHLIST, EXCLUDED_TICKERS, save_watchlist, load_watchlist
from app.data_manager import fetch_and_prepare_data
from app.data_cache import invalidate_cache

class LiveTradingRunner:
    def __init__(self):
        self.is_running = True
        self.logs = []
        self.action_logs = []
        self.trade_history = []
        self.history_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "trade_history.json")
        self.load_trade_history()
        self.config_file = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "runner_config.json")
        self.init_alpaca_adapter()
        self.active_tickers = WATCHLIST.copy()
        self._account_cache = None
        self._account_cache_time = 0.0
        self._positions_cache = None
        self._positions_cache_time = 0.0
        self.highest_prices = {}
        self.position_extremes = {}
        self.intraday_opportunities = {}
        self.ticker_directions = {}
        self.last_exit_times = {}
        self.entry_times = {}
        self._score_warmup_complete = False
        self.pyramid_done = {}  # {ticker: bool} tracks whether a pyramid add has been done for current position
        self.partial_tp_done = {}  # {ticker: bool} tracks whether partial profit scaling has been taken
        self.ticker_consecutive_losses = {}  # {ticker: int} tracks consecutive losses per session to avoid whipsaw losses

        self.screener = UniverseScreener(self._get_alpaca_credentials, self.add_log)
        self.risk_sizer = RiskPositionSizer()
        self.alpha_engine = InstitutionalAlphaEngine()

        self.loop_task = None
        self.order_sync_thread = None
        self._orders_lock = threading.RLock()
        self._orders_refresh_lock = threading.Lock()
        self._orders_cache = []
        self._orders_cache_updated_at = 0.0
        self._orders_cache_error = None
        self._orders_cache_latency_ms = None

        self.strategy_params = self._aggressive_intraday_defaults()
        self.ticker_scores = {}
        self._loaded_strategy_version = None
        self.load_runner_config()
        if self._loaded_strategy_version != "aggressive_intraday_v2":
            self.strategy_params.update(self._aggressive_intraday_defaults())
        self.add_log("📡 [系统初始化完成] Quant AI 日内概率风控与研判引擎已就绪...")
        self.start()

    @staticmethod
    def _aggressive_intraday_defaults() -> Dict:
        return {
            "strategy_version": "aggressive_intraday_v5",
            "strategy_mode": "aggressive_intraday",
            "paper_only_aggressive": True,
            "allow_aggressive_live": False,
            "dynamic_screener_enabled": False,  # Strict focus on 4-stock focus watchlist (SNDK, TSLA, MSTR, NVDA)
            "screener_refresh_seconds": 120,
            "screener_top_actives": 6,
            "screener_top_movers": 4,
            "max_scan_symbols": 14,
            # Strict High-Probability & Risk Controls to prevent losses
            "entry_score_min": 78.0,        # strict entry score threshold >= 78.0
            "full_size_score": 85.0,        # scale to full size at 85.0
            "min_expected_value_r": 0.15,   # require strong positive EV (>= +0.15R)
            "reentry_cooldown_seconds": 300, # 300 seconds (5 min) cooldown to eliminate whipsaw chasing
            "max_concurrent_positions": 2,  # max 2 simultaneous high-conviction positions
            "max_losses_per_ticker_session": 2, # max 2 consecutive losses per symbol per session
            "pyramid_trigger_pct": 0.006,   # 0.6% profit triggers pyramid add
            "min_stock_price": 5.00,
            "buying_power_utilization_pct": 0.95,
            "starter_buying_power_pct": 0.35,
            "max_position_buying_power_pct": 0.95,
            "max_position_risk_pct": 0.030,
            "daily_loss_limit_pct": 0.030,
            "initial_stop_atr_mult": 1.80,
            "stop_min_pct": 0.0080,
            "stop_max_pct": 0.0200,
            "trail_start_pct": 0.0120,
            "trailing_stop_atr_mult": 2.20,
            "trailing_stop_min_pct": 0.0080,
            "trailing_stop_max_pct": 0.0250,
            "minimum_hold_minutes": 4,
            "max_hold_minutes": 300,
            "time_stop_min_score": 52.0,
            "orders_sync_interval_seconds": 2.0,
        }

    # Proxy properties for locks to maintain full backward compatibility
    @property
    def pending_entry_locks(self):
        return self.risk_sizer.pending_entry_locks

    @property
    def pending_exit_locks(self):
        return self.risk_sizer.pending_exit_locks

    def is_entry_locked(self, ticker: str) -> bool:
        return self.risk_sizer.is_entry_locked(ticker)

    def is_exit_locked(self, ticker: str) -> bool:
        return self.risk_sizer.is_exit_locked(ticker)

    def lock_entry(self, ticker: str):
        self.risk_sizer.lock_entry(ticker)

    def unlock_entry(self, ticker: str):
        self.risk_sizer.unlock_entry(ticker)

    def lock_exit(self, ticker: str):
        self.risk_sizer.lock_exit(ticker)

    def unlock_exit(self, ticker: str):
        self.risk_sizer.unlock_exit(ticker)

    def _can_open_short(self, ticker: str) -> bool:
        return self.risk_sizer.can_open_short(ticker, self.adapter)

    def _bg_refresh_account(self):
        try:
            res = self.adapter.get_account_summary()
            if res and res.get("success") is not False:
                res["engine"] = "Python High-Speed Keep-Alive Engine"
                self._account_cache = res
                self._account_cache_time = time.time()
        except Exception as e:
            print(f"[Warning] Account refresh error: {e}")

    def get_cached_account_summary(self) -> Dict:
        now = time.time()
        if self._account_cache is not None:
            if (now - self._account_cache_time) >= 3.0:
                threading.Thread(target=self._bg_refresh_account, daemon=True).start()
            return self._account_cache
        # Initial synchronous fetch on cold startup
        self._bg_refresh_account()
        return self._account_cache or self.adapter.get_account_summary()

    def _bg_refresh_positions(self):
        try:
            res = self.adapter.get_open_positions()
            self._positions_cache = res
            self._positions_cache_time = time.time()
        except Exception:
            pass

    def get_cached_open_positions(self) -> List[Dict]:
        now = time.time()
        if self._positions_cache is not None:
            if (now - self._positions_cache_time) >= 3.0:
                threading.Thread(target=self._bg_refresh_positions, daemon=True).start()
            return self._positions_cache
        self._bg_refresh_positions()
        return self._positions_cache or []

    def load_runner_config(self):
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if "strategy_params" in data and isinstance(data["strategy_params"], dict):
                        saved = data["strategy_params"]
                        saved_mode = saved.get("strategy_mode", "")
                        current_mode = self.strategy_params.get("strategy_mode", "")
                        # Guard: never let a stale config from a different strategy mode
                        # overwrite the engine defaults (e.g. old "dynamic" config clobbering aggressive_intraday_v3)
                        if saved_mode and current_mode and saved_mode != current_mode:
                            print(
                                f"[Config] Skipping runner_config.json — saved mode '{saved_mode}' "
                                f"does not match active mode '{current_mode}'. Using engine defaults."
                            )
                            return
                        self._loaded_strategy_version = saved.get("strategy_version")
                        self.strategy_params.update(saved)
        except Exception as e:
            print(f"Error loading runner_config.json: {e}")

    def save_runner_config(self):
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
        msg = "⏱️ 开盘关盘已 100% 绑定 Alpaca 官方交易所 API 实操时钟 (AUTO_EXCHANGE)。"
        self.save_runner_config()
        self.add_log(msg)
        return {"success": True, "market_mode": "AUTO_EXCHANGE", "message": msg}

    def load_trade_history(self):
        try:
            if os.path.exists(self.history_file):
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.trade_history = data.get("trade_history", [])
                    raw_action_logs = data.get("action_logs", [])
                    self.action_logs = [l for l in raw_action_logs if "Waiting for bar data" not in str(l) and "MU" not in str(l)]
                    raw_logs = data.get("logs", [])
                    self.logs = [l for l in raw_logs if "Waiting for bar data" not in str(l) and "MU" not in str(l)]
        except Exception as e:
            print(f"Error loading trade_history.json: {e}")

    def recalculate_trade_pnls(self):
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
            ticker_queues = {}
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
            print(full_msg)
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
        est = pytz.timezone('America/New_York')
        now = datetime.datetime.now(est)
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

        action_emoji = {"BUY": "🟢", "SELL": "🔴", "SHORT": "🔻", "COVER": "🔼"}.get(action, "⚪")
        pnl_str = f" | PnL: {'+'if pnl>=0 else ''}{pnl:.2f} USD" if pnl != 0.0 else ""
        feed_msg = f"[{timestamp_str}] {action_emoji} [{ticker}] {action} × {shares} shs @ ${price:.2f}{pnl_str} | {reason}"

        self.action_logs.append(feed_msg)
        if len(self.action_logs) > 300:
            self.action_logs.pop(0)

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
        est = pytz.timezone('America/New_York')
        today = datetime.datetime.now(est).strftime("%Y-%m-%d")
        
        def parse_trade_date(t):
            raw = str(t.get("date") or t.get("time") or "").strip()
            return raw[:10] if len(raw) >= 10 else ""

        today_trades = [t for t in self.trade_history if parse_trade_date(t) == today]

        closed_trades = [t for t in today_trades if t.get("action") in ("SELL", "COVER", "PARTIAL_SELL", "PARTIAL_COVER")]
        wins = [t for t in closed_trades if (t.get("pnl") or 0.0) > 0]
        losses = [t for t in closed_trades if (t.get("pnl") or 0.0) < 0]
        realized_pnl = sum((t.get("pnl") or 0.0) for t in closed_trades)

        unrealized_pnl = 0.0
        try:
            open_positions = self.adapter.get_open_positions()
            for pos in open_positions:
                unrealized_pnl += pos.get("unrealized_pnl", 0.0)
        except Exception:
            pass

        alpaca_official_today_pnl = None
        try:
            acc_info = self.get_cached_account_summary()
            if acc_info and acc_info.get("success") and "today_pnl" in acc_info:
                alpaca_official_today_pnl = acc_info.get("today_pnl")
        except Exception:
            pass

        official_pnl = round(alpaca_official_today_pnl, 2) if alpaca_official_today_pnl is not None else round(realized_pnl + unrealized_pnl, 2)
        return {
            "date": today,
            "total_trades": len(today_trades),
            "closed_trades": len(closed_trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(closed_trades) * 100, 1) if closed_trades else 0.0,
            "realized_pnl": round(realized_pnl, 2),
            "alpaca_official_pnl": official_pnl,
            "unrealized_pnl": round(unrealized_pnl, 2),
            "total_pnl": official_pnl,
            "best_trade": round(max((t.get("pnl", 0.0) for t in closed_trades), default=0.0), 2),
            "worst_trade": round(min((t.get("pnl", 0.0) for t in closed_trades), default=0.0), 2)
        }

    def update_tickers(self, new_tickers: List[str]):
        previous_watchlist = load_watchlist() or WATCHLIST.copy()
        cleaned = []
        for t in new_tickers:
            if t and isinstance(t, str):
                sym = t.upper().strip()
                if sym and sym not in cleaned:
                    cleaned.append(sym)
        
        removed_tickers = [t for t in previous_watchlist if t not in cleaned]
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
                            reason="Watchlist Removal Auto Liquidation",
                            order_id=close_res.get("order_id") or close_res.get("id"),
                            order_status=close_res.get("status") or "submitted",
                        )
            except Exception as e:
                self.add_log(f"⚠️ 自选股移除自动清仓警告: {e}")

        if set(cleaned) != set(previous_watchlist):
            self.active_tickers = cleaned
            save_watchlist(cleaned, allow_empty=True)
            self.add_log(f"🔄 已更新手动种子池；Alpaca 日内涨跌幅/活跃榜仍会动态补充: {cleaned}")

    def close_individual_position(self, ticker: str) -> dict:
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
        except Exception as e:
            return {"success": False, "error": str(e)}

    def init_alpaca_adapter(self):
        try:
            api_key, api_secret, base_url = self._get_alpaca_credentials()
            if self._credential_is_configured(api_key) and self._credential_is_configured(api_secret):
                self.adapter = AlpacaAdapter(
                    api_key=api_key,
                    api_secret=api_secret,
                    base_url=base_url
                )
                self.adapter.get_account_summary()
            else:
                self.adapter = MockAlpacaAdapter()
        except Exception:
            self.adapter = MockAlpacaAdapter()

    @staticmethod
    def _get_alpaca_credentials():
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

    @staticmethod
    def _safe_float(value, default: float = 0.0) -> float:
        try:
            number = float(value)
            return number if math.isfinite(number) else float(default)
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _market_date(index_value):
        try:
            if getattr(index_value, "tzinfo", None) is not None and hasattr(index_value, "tz_convert"):
                index_value = index_value.tz_convert("America/New_York")
            return index_value.date()
        except Exception:
            return None

    def _today_session_frame(self, df):
        try:
            last_date = self._market_date(df.index[-1])
            if last_date is None:
                return df
            mask = [self._market_date(value) == last_date for value in df.index]
            session_df = df[mask]
            return session_df if not session_df.empty else df
        except Exception:
            return df

    def _build_intraday_opportunity(self, ticker: str, df, row, prev_row) -> Dict:
        close = self._safe_float(row.get("Close"), 0.0)
        prev_close = self._safe_float(prev_row.get("Close"), close)
        session = self._today_session_frame(df)

        session_open = self._safe_float(session.iloc[0].get("Open"), close)
        session_high = self._safe_float(session["High"].max(), close) if "High" in session else close
        session_low = self._safe_float(session["Low"].min(), close) if "Low" in session else close
        ema_9 = self._safe_float(row.get("EMA_9"), close)
        ema_21 = self._safe_float(row.get("EMA_21"), close)
        prev_ema_21 = self._safe_float(prev_row.get("EMA_21"), prev_close)
        vwap = self._safe_float(row.get("VWAP"), close)
        prev_vwap = self._safe_float(prev_row.get("VWAP"), prev_close)
        atr = max(0.0, self._safe_float(row.get("ATR"), close * 0.004))
        rvol = max(0.0, self._safe_float(row.get("RVOL"), 1.0))

        base_3 = self._safe_float(df.iloc[-4].get("Close"), prev_close) if len(df) >= 4 else prev_close
        base_10 = self._safe_float(df.iloc[-11].get("Close"), base_3) if len(df) >= 11 else base_3
        session_move_pct = ((close / session_open) - 1.0) * 100.0 if session_open > 0 else 0.0
        high_to_now_pct = ((close / session_high) - 1.0) * 100.0 if session_high > 0 else 0.0
        low_to_now_pct = ((close / session_low) - 1.0) * 100.0 if session_low > 0 else 0.0
        up_from_open_pct = ((session_high / session_open) - 1.0) * 100.0 if session_open > 0 else 0.0
        down_from_open_pct = ((session_low / session_open) - 1.0) * 100.0 if session_open > 0 else 0.0
        session_range_pct = ((session_high - session_low) / session_open) * 100.0 if session_open > 0 else 0.0
        momentum_3_pct = ((close / base_3) - 1.0) * 100.0 if base_3 > 0 else 0.0
        momentum_10_pct = ((close / base_10) - 1.0) * 100.0 if base_10 > 0 else 0.0
        atr_pct = (atr / close) * 100.0 if close > 0 else 0.0
        price_range = max(0.0, session_high - session_low)
        range_position = ((close - session_low) / price_range) if price_range > 0 else 0.5

        activity_score = (
            min(18.0, max(0.0, session_range_pct) * 3.5)
            + min(12.0, max(0.0, rvol - 1.0) * 8.0)
            + min(8.0, max(0.0, atr_pct) * 5.0)
        )
        long_score = activity_score
        short_score = activity_score

        if close > vwap:
            long_score += 12.0
        else:
            short_score += 12.0
        if ema_9 > ema_21:
            long_score += 12.0
        else:
            short_score += 12.0

        if momentum_3_pct >= 0.20:
            long_score += min(10.0, 6.0 + momentum_3_pct * 4.0)
        elif momentum_3_pct <= -0.20:
            short_score += min(10.0, 6.0 + abs(momentum_3_pct) * 4.0)
        if momentum_10_pct >= 0.45:
            long_score += min(10.0, 6.0 + momentum_10_pct * 2.0)
        elif momentum_10_pct <= -0.45:
            short_score += min(10.0, 6.0 + abs(momentum_10_pct) * 2.0)

        if session_move_pct >= 1.0:
            long_score += min(15.0, 8.0 + session_move_pct * 2.0)
        elif session_move_pct <= -1.0:
            short_score += min(15.0, 8.0 + abs(session_move_pct) * 2.0)
        if range_position >= 0.68:
            long_score += 8.0 + min(4.0, (range_position - 0.68) * 12.0)
        elif range_position <= 0.32:
            short_score += 8.0 + min(4.0, (0.32 - range_position) * 12.0)

        long_breakout = (
            close > vwap and ema_9 > ema_21 and momentum_3_pct > 0.15
            and high_to_now_pct >= -0.65
        )
        short_breakdown = (
            close < vwap and ema_9 < ema_21 and momentum_3_pct < -0.15
            and low_to_now_pct <= 0.90
        )
        if long_breakout:
            long_score += 8.0
        if short_breakdown:
            short_score += 8.0

        reversal_short = (
            up_from_open_pct >= 1.20
            and high_to_now_pct <= -0.80
            and close < vwap
            and momentum_3_pct < -0.05
        )
        reversal_long = (
            down_from_open_pct <= -1.20
            and low_to_now_pct >= 0.80
            and close > vwap
            and momentum_3_pct > 0.05
        )
        if reversal_short:
            short_score += 18.0
        if reversal_long:
            long_score += 18.0

        long_score = round(max(0.0, min(100.0, long_score)), 1)
        short_score = round(max(0.0, min(100.0, short_score)), 1)
        # Relaxed directional classification: gap of 3.0 (was 5.0) → fewer NEUTRAL signals
        if abs(long_score - short_score) < 3.0:
            direction = "NEUTRAL"
            score = max(long_score, short_score)
            regime = "RANGE"
        elif long_score > short_score:
            direction = "LONG"
            score = long_score
            regime = "LONG_REVERSAL" if reversal_long else "LONG_TREND"
        else:
            direction = "SHORT"
            score = short_score
            regime = "SHORT_REVERSAL" if reversal_short else "SHORT_TREND"

        prev_long_structure = prev_close > prev_vwap or prev_close > prev_ema_21
        prev_short_structure = prev_close < prev_vwap or prev_close < prev_ema_21
        # Strict entry confirmation requiring VWAP + EMA alignment & positive momentum direction
        vwap_ema_long_alignment = close > vwap and ema_9 > ema_21 and momentum_3_pct > 0.10
        vwap_ema_short_alignment = close < vwap and ema_9 < ema_21 and momentum_3_pct < -0.10
        long_confirmed = (
            (long_breakout and (prev_long_structure or momentum_3_pct >= 0.50 or reversal_long))
            or (vwap_ema_long_alignment and direction == "LONG" and score >= 78.0)
        )
        short_confirmed = (
            (short_breakdown and (prev_short_structure or momentum_3_pct <= -0.50 or reversal_short))
            or (vwap_ema_short_alignment and direction == "SHORT" and score >= 78.0)
        )
        
        vwap_dist_pct = ((close - vwap) / vwap * 100.0) if vwap > 0 else 0.0
        rsi = self._safe_float(row.get("RSI"), 50.0)

        # Pure ML Model Control: Traditional rule-based overextension blockers removed.
        is_overextended = False

        # Stock-adaptive ATR Noise Stop:
        # High volatility / high ATR stocks (e.g. CRCL/SNDK with ATR% >= 2.0%) get expanded initial stop buffer to avoid micro noise shakeout
        initial_mult = self._safe_float(self.strategy_params.get("initial_stop_atr_mult"), 1.60)
        if atr_pct >= 2.0:
            initial_mult = max(1.85, initial_mult * 1.15)
        stop_pct = min(
            self._safe_float(self.strategy_params.get("stop_max_pct"), 0.0250),
            max(
                self._safe_float(self.strategy_params.get("stop_min_pct"), 0.0050),
                initial_mult * (atr / close if close > 0 else 0.0050),
            ),
        )

        # Evaluate Institutional Composite Alpha Factors
        alpha_eval = self.alpha_engine.evaluate_composite_alpha(row=row, prev_row=prev_row)

        is_trap = alpha_eval.get("is_trap", False)
        trap_reason = alpha_eval.get("trap_reason", "")

        # Anti-Bull/Bear Trap Engine: Convert false breakouts into active SHORT/LONG opportunities
        if is_trap and ("Bull Trap" in trap_reason or "Upper Wick" in trap_reason or "Ask Depth" in trap_reason):
            long_confirmed = False
            if alpha_eval["composite_alpha_score"] <= -45.0:
                direction = "SHORT"
                short_confirmed = True
        elif is_trap and ("Bear Trap" in trap_reason or "Lower Wick" in trap_reason or "Bid Depth" in trap_reason):
            short_confirmed = False
            if alpha_eval["composite_alpha_score"] >= 45.0:
                direction = "LONG"
                long_confirmed = True

        opp = {
            "ticker": ticker,
            "direction": direction,
            "regime": regime,
            "score": score,
            "long_score": long_score,
            "short_score": short_score,
            "composite_alpha_score": alpha_eval["composite_alpha_score"],
            "alpha_ofi": alpha_eval["alpha_ofi"],
            "alpha_micro": alpha_eval["alpha_micro"],
            "alpha_ou": alpha_eval["alpha_ou"],
            "alpha_lead_lag": alpha_eval["alpha_lead_lag"],
            "is_trap": is_trap,
            "trap_reason": trap_reason,
            "session_move_pct": round(session_move_pct, 2),
            "session_range_pct": round(session_range_pct, 2),
            "high_to_now_pct": round(high_to_now_pct, 2),
            "low_to_now_pct": round(low_to_now_pct, 2),
            "momentum_3_pct": round(momentum_3_pct, 2),
            "momentum_10_pct": round(momentum_10_pct, 2),
            "rvol": round(rvol, 2),
            "atr_pct": round(atr_pct, 2),
            "price": round(close, 4),
            "_entry_confirmed": long_confirmed if direction == "LONG" else short_confirmed,
            "_stop_pct": stop_pct,
            "_vwap_dist_pct": vwap_dist_pct,
            "_rsi": rsi,
            "_is_overextended": is_overextended,
            "_ema_9": ema_9,
            "_ema_21": ema_21,
            "_prev_ema_21": prev_ema_21,
            "_vwap": vwap,
            "_prev_vwap": prev_vwap,
            "_prev_close": prev_close,
            "_atr": atr,
        }


        # Evaluate Probabilistic Win Rate P_win and Expected Value E[PnL]
        prob_eval = evaluate_mathematical_expectation(opp, self.strategy_params)
        opp.update(prob_eval)

        # Opening Catalyst Zero-Delay Trigger (9:30 - 9:45 EST Blitz):
        # Bypasses multi-bar lag for high RVOL / high volatility catalyst stocks
        est = pytz.timezone("America/New_York")
        now_ny = datetime.datetime.now(est)
        ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0
        is_opening_blitz = (now_ny.weekday() <= 4) and (9.50 <= ny_time < 9.75)
        if not opp.get("_entry_confirmed", False):
            from app.broker.probability_engine import evaluate_zero_delay_opening_trigger
            if evaluate_zero_delay_opening_trigger(opp, is_opening_blitz):
                opp["_entry_confirmed"] = True
                opp["_zero_delay_triggered"] = True

        return opp

    def _aggressive_orders_allowed(self) -> bool:
        if not self.strategy_params.get("paper_only_aggressive", True):
            return True
        if self.strategy_params.get("allow_aggressive_live", False):
            return True
        if isinstance(self.adapter, MockAlpacaAdapter):
            return True
        try:
            _key, _secret, base_url = self._get_alpaca_credentials()
            return "paper-api.alpaca.markets" in str(base_url or "").lower()
        except Exception:
            return False

    def _refresh_intraday_universe(self, user_watchlist: List[str], active_pos_tickers) -> List[str]:
        return self.screener.refresh_intraday_universe(
            user_watchlist=user_watchlist,
            active_pos_tickers=active_pos_tickers,
            strategy_params=self.strategy_params,
            ticker_scores=self.ticker_scores,
        )

    def _evaluate_aggressive_intraday(
        self,
        ticker: str,
        opportunity: Dict,
        current_shares: int,
        avg_cost: float,
        open_position_count: int,
    ):
        close = self._safe_float(opportunity.get("price"), 0.0)
        direction = opportunity.get("direction", "NEUTRAL")
        p_win_pct = opportunity.get("win_rate_pct", 50.0)
        ev_r = opportunity.get("expected_value_r", 0.0)
        is_pos_ev = opportunity.get("is_positive_ev", False)

        base_reason = (
            f"[{opportunity.get('regime')}] {direction} | P_win={p_win_pct:.1f}% | "
            f"E[PnL]={ev_r:+.2f}R | 日内={opportunity.get('session_move_pct', 0):+.2f}% | "
            f"M3={opportunity.get('momentum_3_pct', 0):+.2f}% | RVOL={opportunity.get('rvol', 1):.2f}x"
        )

        if current_shares == 0:
            self.position_extremes.pop(ticker, None)
            # Reset pyramid and partial TP state when flat
            if ticker in self.pyramid_done:
                del self.pyramid_done[ticker]
            if ticker in self.partial_tp_done:
                del self.partial_tp_done[ticker]
            from app.broker.universe_screener import is_valid_quality_stock_symbol
            min_price = self._safe_float(self.strategy_params.get("min_stock_price"), 5.00)

            # Quality Stock & Warrant/Unit Filter (dynamic quality screening instead of static blacklists)
            if not is_valid_quality_stock_symbol(ticker):
                return "HOLD", f"{base_reason} | 标的属于权证/衍生单元 (Warrant/Unit)，拒绝交易"

            # Per-Symbol Consecutive Loss Guard
            max_losses = int(self.strategy_params.get("max_losses_per_ticker_session", 2))
            if self.ticker_consecutive_losses.get(ticker, 0) >= max_losses:
                return "HOLD", f"{base_reason} | 🛑 该标的单日已连续止损 {self.ticker_consecutive_losses[ticker]} 次，触发熔断停牌避险"

            if close < min_price:
                return "HOLD", f"{base_reason} | 股价低于 ${min_price:.2f} (${close:.2f})，拒绝低价毛票/仙股"

            # HRT-Grade ML Quantitative Alpha Model Entry Evaluation:
            # Driven directly by ML Probabilistic Mathematical Expectation E[PnL] >= +0.15R and P_win
            if direction == "NEUTRAL" or not opportunity.get("_entry_confirmed", False):
                return "HOLD", f"{base_reason} | 未达到 HRT 信号确认门槛"
            if not is_pos_ev:
                return "HOLD", f"{base_reason} | HRT 期望值未达标 (E[PnL]={ev_r:+.2f}R < +0.15R 或 P_win未达标)，拒绝盲目交易"
            
            # RVOL False Breakdown Guard (要求相对成交量放量确认 RVOL >= 1.25x)
            rvol_val = self._safe_float(opportunity.get("rvol"), 1.0)
            min_rvol = self._safe_float(self.strategy_params.get("min_entry_rvol"), 1.25)
            if rvol_val < min_rvol:
                return "HOLD", f"{base_reason} | ⚠️ 无量假突破拦截 (RVOL={rvol_val:.2f}x < {min_rvol:.2f}x)，缺乏机构资金放量确认"
            last_exit = self.last_exit_times.get(ticker)
            cooldown = self._safe_float(self.strategy_params.get("reentry_cooldown_seconds"), 300.0)
            if last_exit and (time.time() - last_exit) < cooldown:
                remain = int(cooldown - (time.time() - last_exit))
                return "HOLD", f"{base_reason} | 平仓冷却中 ({remain}s 剩余)，避免同一走势反复追单"
            if open_position_count >= int(self.strategy_params.get("max_concurrent_positions", 2)):
                return "HOLD", f"{base_reason} | 已达最大同时持仓数"
            if not self._aggressive_orders_allowed():
                return "HOLD", f"{base_reason} | 激进 buying-power 模式默认只允许 Paper"
            if direction == "SHORT" and not self._can_open_short(ticker):
                return "HOLD", f"{base_reason} | Alpaca Asset 当前不可直接卖空/需要 locate"
            return ("BUY" if direction == "LONG" else "SHORT"), f"{base_reason} | 正期望值 (E[R]={ev_r:+.2f}R)，按 buying power 建仓"

        side = "LONG" if current_shares > 0 else "SHORT"
        state = self.position_extremes.get(ticker)
        if not state or state.get("side") != side:
            state = {"side": side, "best_price": avg_cost or close}
            self.position_extremes[ticker] = state
        if side == "LONG":
            state["best_price"] = max(self._safe_float(state.get("best_price"), close), close)
        else:
            state["best_price"] = min(self._safe_float(state.get("best_price"), close), close)

        entry_at = self.entry_times.setdefault(ticker, datetime.datetime.now())
        minutes_held = max(0.0, (datetime.datetime.now() - entry_at).total_seconds() / 60.0)
        pnl_pct = ((close - avg_cost) / avg_cost) if side == "LONG" and avg_cost > 0 else ((avg_cost - close) / avg_cost if avg_cost > 0 else 0.0)
        stop_pct = self._safe_float(opportunity.get("_stop_pct"), 0.0100)
        
        # Breakeven Stop: If partial TP has been taken, protect remaining shares at cost price (avg_cost)
        if self.partial_tp_done.get(ticker, False) and pnl_pct <= 0.0:
            return ("SELL" if side == "LONG" else "COVER"), f"{base_reason} | 🛡️ 半仓止盈后触及保本线 (${avg_cost:.2f})，平余仓保本离场"

        hard_stop = (side == "LONG" and close <= avg_cost * (1.0 - stop_pct)) or (side == "SHORT" and close >= avg_cost * (1.0 + stop_pct))
        if hard_stop:
            self.ticker_consecutive_losses[ticker] = self.ticker_consecutive_losses.get(ticker, 0) + 1
            return ("SELL" if side == "LONG" else "COVER"), f"{base_reason} | 初始硬止损 {stop_pct*100:.2f}% (单日第 {self.ticker_consecutive_losses[ticker]} 次)"

        # ─── Alpha Decay Exit (Alpha 动能衰减离场) ──────────────────────────────────
        alpha_score = self._safe_float(opportunity.get("composite_alpha_score"), 0.0)
        if side == "LONG" and alpha_score < 15.0 and pnl_pct >= 0.0025:
            return "SELL", f"{base_reason} | 📉 Composite Alpha 动能衰减 (Alpha={alpha_score:+.1f} < +15.0)，主动落袋锁利"
        if side == "SHORT" and alpha_score > -15.0 and pnl_pct >= 0.0025:
            return "COVER", f"{base_reason} | 📈 Composite Alpha 做空动能衰减 (Alpha={alpha_score:+.1f} > -15.0)，主动平空锁利"

        # ─── Partial Take-Profit (分批止盈/锁利) ──────────────────────────────────
        # When unrealized gain reaches >= 1.2% (or 1.2 * stop_pct) and position has > 1 share,
        # scale out 50% to lock in profit, then set Breakeven stop for the rest!
        tp1_pct = max(0.0100, 1.2 * stop_pct)
        if pnl_pct >= tp1_pct and not self.partial_tp_done.get(ticker, False) and abs(current_shares) > 1:
            action_str = "PARTIAL_SELL" if side == "LONG" else "PARTIAL_COVER"
            est_pnl_usd = pnl_pct * close * abs(current_shares) / 2.0
            return action_str, (
                f"{base_reason} | 🟢 [分批止盈 50%] 浮盈 +{pnl_pct*100:.2f}% (预估锁利 +${est_pnl_usd:.2f}) — "
                f"落袋为安半仓，余仓开启移动止盈与保本风控"
            )

        atr = self._safe_float(opportunity.get("_atr"), close * 0.004)
        regime = opportunity.get("regime", "RANGE")
        atr_mult = 2.80 if "REVERSAL" in regime else self._safe_float(self.strategy_params.get("trailing_stop_atr_mult"), 2.20)
        max_trail = 0.0400 if "REVERSAL" in regime else self._safe_float(self.strategy_params.get("trailing_stop_max_pct"), 0.0250)

        trail_pct = min(
            max_trail,
            max(
                self._safe_float(self.strategy_params.get("trailing_stop_min_pct"), 0.0080),
                atr_mult * (atr / close if close > 0 else 0.0),
            ),
        )
        trail_start = max(self._safe_float(self.strategy_params.get("trail_start_pct"), 0.0120), stop_pct)
        best_price = self._safe_float(state.get("best_price"), close)
        trail_hit = False
        if pnl_pct >= trail_start:
            trail_hit = (side == "LONG" and close <= best_price * (1.0 - trail_pct)) or (side == "SHORT" and close >= best_price * (1.0 + trail_pct))
        if trail_hit:
            return ("SELL" if side == "LONG" else "COVER"), f"{base_reason} | 趋势追踪回撤 {trail_pct*100:.2f}% 触发全平"

        min_hold = self._safe_float(self.strategy_params.get("minimum_hold_minutes"), 4.0)
        if minutes_held >= min_hold:
            prev_close = self._safe_float(opportunity.get("_prev_close"), close)
            if side == "LONG":
                invalid_now = close < opportunity.get("_ema_21", close) and close < opportunity.get("_vwap", close)
                invalid_prev = prev_close < opportunity.get("_prev_ema_21", prev_close) and prev_close < opportunity.get("_prev_vwap", prev_close)
                if invalid_now and invalid_prev and opportunity.get("short_score", 0.0) >= 70.0:
                    return "SELL", f"{base_reason} | 连续两根跌破 EMA21/VWAP，长趋势失效"
            else:
                invalid_now = close > opportunity.get("_ema_21", close) and close > opportunity.get("_vwap", close)
                invalid_prev = prev_close > opportunity.get("_prev_ema_21", prev_close) and prev_close > opportunity.get("_prev_vwap", prev_close)
                if invalid_now and invalid_prev and opportunity.get("long_score", 0.0) >= 70.0:
                    return "COVER", f"{base_reason} | 连续两根收复 EMA21/VWAP，空趋势失效"

        max_hold = self._safe_float(self.strategy_params.get("max_hold_minutes"), 300.0)
        same_side_score = opportunity.get("long_score", 0.0) if side == "LONG" else opportunity.get("short_score", 0.0)
        if minutes_held >= max_hold and same_side_score < self._safe_float(self.strategy_params.get("time_stop_min_score"), 52.0) and pnl_pct <= 0.0:
            return ("SELL" if side == "LONG" else "COVER"), f"{base_reason} | 尾段趋势消失且未盈利"

        # ─── Pyramiding Buy / Short (浮盈加仓/补仓) ─────────────────────────────
        # Fires once per position when:
        #   - Position is profitable >= 0.4% (configurable via pyramid_trigger_pct)
        #   - Same-side score strong (>= entry_score_min) AND positive EV >= +0.20R
        #   - RVOL >= 1.2 and trend structure still valid above VWAP + EMA21
        #   - Not already pyramided for this trade (pyramid_done[ticker] == False)
        pyramid_threshold_pct = self._safe_float(self.strategy_params.get("pyramid_trigger_pct"), 0.004)
        pyramid_min_score = self._safe_float(self.strategy_params.get("entry_score_min"), 78.0)
        can_pyramid = (
            pnl_pct >= pyramid_threshold_pct
            and same_side_score >= pyramid_min_score
            and is_pos_ev
            and ev_r >= 0.20
            and self._safe_float(opportunity.get("rvol"), 1.0) >= 1.2
            and not self.pyramid_done.get(ticker, False)
            and self._aggressive_orders_allowed()
        )
        if can_pyramid:
            if side == "LONG":
                trend_ok = close >= opportunity.get("_vwap", close) and close >= opportunity.get("_ema_21", close)
            else:
                trend_ok = close <= opportunity.get("_vwap", close) and close <= opportunity.get("_ema_21", close)
            if trend_ok:
                action_str = "PYRAMID_BUY" if side == "LONG" else "PYRAMID_SHORT"
                return action_str, (
                    f"{base_reason} | 📈 [浮盈加仓 +{pnl_pct*100:.2f}% PnL] 趋势强劲 Score={same_side_score:.0f} / "
                    f"E[R]={ev_r:+.2f}R — 触发 {action_str}，顺势补强"
                )

        return "HOLD", f"{base_reason} | {side} 趋势仍有效，整仓持有，不做碎片止盈"

    def _size_aggressive_entry(self, account: Dict, close_price: float, opportunity: Dict) -> Dict:
        return self.risk_sizer.size_aggressive_entry(
            account=account,
            close_price=close_price,
            opportunity=opportunity,
            strategy_params=self.strategy_params,
            prob_eval=opportunity
        )

    def _size_probe_entry(self, account: Dict, close_price: float, opportunity: Dict) -> Dict:
        return self.risk_sizer.size_probe_entry(
            account=account,
            close_price=close_price,
            opportunity=opportunity,
            strategy_params=self.strategy_params,
            prob_eval=opportunity
        )

    def _size_pyramid_entry(self, account: Dict, close_price: float, opportunity: Dict) -> Dict:
        return self.risk_sizer.size_pyramid_entry(
            account=account,
            close_price=close_price,
            opportunity=opportunity,
            strategy_params=self.strategy_params,
            prob_eval=opportunity
        )

    def start(self, strategy_params: Optional[Dict] = None, tickers: Optional[List[str]] = None, **kwargs):
        if getattr(self, '_loop_thread', None) is not None and self._loop_thread.is_alive():
            self.add_log("[Warning] 交易机器人已在运行中，无需重复启动。")
            return False

        try:
            invalidate_cache()
            self.highest_prices.clear()
            self.position_extremes.clear()
            self._score_warmup_complete = False
            self.add_log("🧹 [手动启动重置] 已强制清空上一日盘后缓存与最高价记录，初始化全新交易周期。")
        except Exception as e:
            print(f"Cache clear warning on start: {e}")
            
        if strategy_params:
            self.strategy_params.update(strategy_params)

        if tickers:
            self.update_tickers(tickers)

        self.save_runner_config()
        
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
            self.add_log(f"⚠️ [Alpaca 连接失败警报] API 密钥配置存在异常 ({str(e)})，暂降级至【本地虚拟盘模拟模式】！")
        self.is_running = True
        self._start_order_sync_worker()
        self.add_log(f"🤖 【AI 24/7 全自动托管开启】系统已进入无人值守全自动轮询模式！监控标的({len(self.active_tickers)}): {self.active_tickers}")
        
        def start_background_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._run_loop())
        t = threading.Thread(target=start_background_loop, name="quant-ai-engine-loop", daemon=True)
        self._loop_thread = t
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
        if self.is_running:
            self.stop()
            return {"status": "stopped", "is_running": False, "message": "已手动关闭量化交易系统"}
        else:
            self.start(strategy_params=strategy_params, tickers=tickers)
            return {"status": "started", "is_running": True, "message": "已手动启动量化交易系统"}

    def submit_extended_hours_order(self, symbol: str, qty: int, side: str, limit_price: float) -> Dict:
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
            "ticker_directions": self.ticker_directions,
            "intraday_opportunities": sorted(
                self.intraday_opportunities.values(),
                key=lambda item: item.get("score", 0.0),
                reverse=True,
            ),
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
        return self.refresh_alpaca_orders() if force_refresh else self._cached_orders_snapshot()

    def is_market_open(self) -> bool:
        est = pytz.timezone('America/New_York')
        now_ny = datetime.datetime.now(est)
        is_weekday = now_ny.weekday() <= 4
        ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0
        return is_weekday and (9.5 <= ny_time < 16.0)

    def is_eod_no_entry_window(self) -> bool:
        est = pytz.timezone('America/New_York')
        now_ny = datetime.datetime.now(est)
        if now_ny.weekday() > 4:
            return False
        ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0
        return 15.9167 <= ny_time < 16.0

    def check_and_trigger_eod_close(self, positions_list: list) -> bool:
        if not positions_list:
            return False
        est = pytz.timezone('America/New_York')
        now_ny = datetime.datetime.now(est)
        if now_ny.weekday() > 4:
            return False
        ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0
        if not (15.9833 <= ny_time < 16.0):
            return False

        today = now_ny.date()
        if getattr(self, "_eod_liquidation_done_date", None) == today:
            return True  # Already performed EOD liquidation once for today's session! Do not repeat!

        seconds_left = (16.0 - ny_time) * 3600.0
        if 0.0 < seconds_left <= 60.0:
            self.add_log(f"🌇 [美东 15:59 关盘前 1 分钟终极清场风控] 距关盘仅剩 {seconds_left:.0f} 秒！执行一次性【双重清场】：全量撤销所有挂单 + 强行全平 {len(positions_list)} 笔持仓，确保零挂单零持仓过夜...")
            self._eod_liquidation_done_date = today  # Mark as executed once today!
            try:
                if hasattr(self.adapter, "cancel_all_orders"):
                    c_res = self.adapter.cancel_all_orders()
                    self.add_log(f"🧹 [双重清场 Step 1/2] 已全量撤销挂单: {c_res.get('message', 'All pending orders canceled.')}")
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
                            reason="EOD Single Liquidation (日内关盘前无条件撤单平仓·只卖一次不重复)"
                        )
                return True
            except Exception as e:
                self.add_log(f"⚠️ [尾盘双重清场异常]: {str(e)}")
        return False

    async def _run_loop(self):
        while self.is_running:
            try:
                is_open = self.is_market_open()
                est = pytz.timezone('America/New_York')
                now_ny = datetime.datetime.now(est)
                ny_time = now_ny.hour + now_ny.minute / 60.0 + now_ny.second / 3600.0
                is_market_opening_window = (now_ny.weekday() <= 4) and (9.50 <= ny_time < 9.75)

                if is_open:
                    self._afterhours_scan_logged = False
                    if is_market_opening_window:
                        if not getattr(self, "_opening_blitz_logged", False):
                            self.add_log(f"⚡ [开盘黄金 Blitz 9:30-9:45 EST] 开启 3 秒极速高频秒开枪！监控池 [{len(self.active_tickers)} 支标的]...")
                            self._opening_blitz_logged = True
                    else:
                        self._opening_blitz_logged = False
                        if not getattr(self, "_intraday_scan_logged", False):
                            self.add_log(f"📡 [美股开盘交易中·全频段扫描发单] 正在研判监控池股票 [{len(self.active_tickers)} 支标的]...")
                            self._intraday_scan_logged = True
                else:
                    self._opening_blitz_logged = False
                    self._intraday_scan_logged = False
                    if not getattr(self, "_afterhours_scan_logged", False):
                        self.add_log(f"🌙 [美股盘后研判/休市监控中] 24/7 持续实时计算多因子与形态（休市期间仅研判记录，暂停实盘买卖发单）...")
                        self._afterhours_scan_logged = True
                
                # Pre-market Catalyst Pre-loader (9:15 - 9:30 EST)
                if (now_ny.weekday() <= 4) and (9.25 <= ny_time < 9.50) and self.strategy_params.get("dynamic_screener_enabled", False) and not getattr(self, "_premarket_preloaded", False):
                    user_wl = load_watchlist() or WATCHLIST.copy()
                    self.active_tickers = self.screener.preload_premarket_catalysts(user_wl)
                    self._premarket_preloaded = True
                elif ny_time >= 9.50:
                    self._premarket_preloaded = False
                
                try:
                    positions_list = self.adapter.get_open_positions()
                    positions_by_ticker = {pos['ticker']: pos for pos in positions_list if pos.get('ticker')}
                    active_pos_tickers = set(positions_by_ticker.keys())
                    
                    for pos_ticker in active_pos_tickers:
                        self.unlock_entry(pos_ticker)
                    for lock_ticker in list(self.pending_exit_locks.keys()):
                        if lock_ticker not in active_pos_tickers:
                            self.unlock_exit(lock_ticker)

                    if self.check_and_trigger_eod_close(positions_list):
                        await asyncio.sleep(30)
                        continue
                except Exception as e:
                    self.add_log(f"⚡ [Alpaca 持仓 Rate-Limit 避让生效] {str(e)} -> 自动使用上一轮已知持仓无缝继续执行！")
                    positions_list = getattr(self, "_last_known_positions_list", [])
                    positions_by_ticker = {pos['ticker']: pos for pos in positions_list if pos.get('ticker')}
                    active_pos_tickers = set(positions_by_ticker.keys())

                user_watchlist = load_watchlist()
                if not user_watchlist:
                    user_watchlist = WATCHLIST.copy()
                
                self.active_tickers = self._refresh_intraday_universe(user_watchlist, active_pos_tickers)
                scan_passes = 3 if is_market_opening_window else 1
                cycle_new_entries = 0
                for pass_idx in range(scan_passes):
                    if not self.is_running:
                        break
                    if pass_idx > 0:
                        await asyncio.sleep(3)

                    if not hasattr(self, "_ticker_df_cache"):
                        self._ticker_df_cache = {}

                    self.active_tickers.sort(key=lambda sym: self.ticker_scores.get(sym, 0.0), reverse=True)
                    for ticker in self.active_tickers:
                        if not self.is_running:
                            break
                        try:
                            df = None
                            try:
                                df = fetch_and_prepare_data(ticker, period="3d", interval="1m")
                                if df is not None and not df.empty and len(df) >= 2:
                                    self._ticker_df_cache[ticker] = df
                            except Exception as fetch_err:
                                if "429" in str(fetch_err) or "rate limit" in str(fetch_err).lower():
                                    df = self._ticker_df_cache.get(ticker)
                                    if df is not None:
                                        self.add_log(f"⚡ [{ticker}] Alpaca Rate-Limit 避让生效：已成功无缝使用缓存数据，持续监控！")

                            if ticker in EXCLUDED_TICKERS:
                                continue
                            if df is None or df.empty or len(df) < 2:
                                continue

                            # Rate-limit safety throttling (1.0s) for calm, comfortable reading pace
                            await asyncio.sleep(1.0)
                                
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

                            ema_9 = float(row.get('EMA_9', close_price))
                            ema_21 = float(row.get('EMA_21', close_price))
                            rvol = float(row.get('RVOL', 1.0))
                            atr = float(row.get('ATR', close_price * 0.01))
                            opportunity = self._build_intraday_opportunity(ticker, df, row, prev_row)
                            live_score = opportunity["score"]
                            self.ticker_scores[ticker] = live_score
                            self.ticker_directions[ticker] = opportunity["direction"]
                            self.intraday_opportunities[ticker] = {
                                key: value for key, value in opportunity.items() if not key.startswith("_")
                            }
                            action, reason = self._evaluate_aggressive_intraday(
                                ticker=ticker,
                                opportunity=opportunity,
                                current_shares=current_shares,
                                avg_cost=avg_cost,
                                open_position_count=len(positions_list),
                            )
                            if current_shares == 0 and action in ("BUY", "SHORT"):
                                if not self._score_warmup_complete:
                                    action = "HOLD"
                                    reason += " | 首轮只完成全池评分，下一轮按最高分优先执行"
                                elif cycle_new_entries >= 1:
                                    action = "HOLD"
                                    reason += " | 本轮已提交一笔新仓，等待 buying power 刷新"

                            account_summary = self.adapter.get_account_summary()
                            total_eq = self._safe_float(account_summary.get('equity'), 100000.0)
                            daily_loss_limit_pct = self.strategy_params.get("daily_loss_limit_pct", 0.040)
                            
                            today_str = datetime.datetime.now().strftime("%Y-%m-%d")
                            today_trades_pnl = sum(t.get("pnl", 0.0) for t in self.trade_history if t.get("date") == today_str)
                            open_pnl = sum((p.get("unrealized_pnl", 0.0)) for p in positions_list)
                            official_today_pnl = account_summary.get("today_pnl")
                            estimated_today_pnl = self._safe_float(official_today_pnl, today_trades_pnl + open_pnl) if official_today_pnl is not None else (today_trades_pnl + open_pnl)
                            est_daily_pnl_pct = estimated_today_pnl / total_eq if total_eq > 0 else 0.0

                            if est_daily_pnl_pct <= -daily_loss_limit_pct and action in ("BUY", "SHORT"):
                                action = "HOLD"
                                reason = f"[DailyLossLimit] Daily drawdown ({est_daily_pnl_pct*100:.2f}%) reached max limit (-{daily_loss_limit_pct*100:.2f}%). Blocked new entry order."

                            allowed_entry_symbols = set(user_watchlist)
                            if ticker not in allowed_entry_symbols and action in ("BUY", "SHORT"):
                                action = "HOLD"
                                reason = f"[{ticker}] 不在 Watchlist/Alpaca 日内候选池，保持 Exit-Only。"

                            if self.is_eod_no_entry_window() and action in ("BUY", "SHORT", "PYRAMID_BUY"):
                                action = "HOLD"
                                reason = f"[{ticker}] EOD No-Entry Window (15:45-16:00 EST). Blocked new entry order."

                            if action in ("BUY", "SHORT") and self.is_entry_locked(ticker):
                                action = "HOLD"
                                reason = f"[{ticker}] Pending entry order lock active. Blocked duplicate entry."
                            elif action in ("SELL", "COVER", "PARTIAL_SELL", "PARTIAL_COVER") and self.is_exit_locked(ticker):
                                action = "HOLD"
                                reason = f"[{ticker}] Pending exit order lock active. Blocked duplicate exit."

                            vwap   = float(row.get('VWAP',   close_price))
                            rsi    = float(row.get('RSI',    50.0))
                            regime = opportunity.get("regime", "RANGE")
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
                                pos_label = "📡 [系统开盘中·空仓研判] 正在全频段扫描研判中"

                            alerts = [
                                f"🎯 {opportunity['direction']} Score:{live_score:.1f}",
                                f"P_win:{opportunity.get('win_rate_pct', 50):.0f}%",
                                f"E[R]:{opportunity.get('expected_value_r', 0):+.2f}R",
                            ]
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
                            elif action in ("PYRAMID_BUY", "PYRAMID_SHORT"):
                                decision_icon = f"📈 {action} (浮盈加仓)"
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

                            if action == "BUY" and current_shares == 0:
                                if not is_open:
                                    self.add_log(f"🌙 [盘后研判/休市记录] [{ticker}] 触发 BUY 买点信号 (AI Score: {live_score}分, P_win: {opportunity.get('win_rate_pct')}%) | 非盘中时段，仅保留研判日志。")
                                else:
                                    account = self.adapter.get_account_summary()
                                    full_score_target = self._safe_float(self.strategy_params.get("full_size_score"), 75.0)
                                    is_probe = live_score < full_score_target
                                    sizing = self._size_probe_entry(account, close_price, opportunity) if is_probe else self._size_aggressive_entry(account, close_price, opportunity)
                                    shares = sizing["shares"]
                                    if shares <= 0:
                                        self.add_log(f"⚠️ [{ticker}] buying power 不足以购买 1 股，跳过本次信号。")
                                        continue

                                    client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}-ENTRY"
                                    self.lock_entry(ticker)
                                    self.entry_times[ticker] = datetime.datetime.now()

                                    entry_type_str = "🧪 PROBE STARTER (25% 试探建仓)" if is_probe else "🚀 FULL SIZE (大仓位进场)"
                                    self.add_log(
                                        f"🛒 [{ticker}] LONG {live_score:.1f}分 ({entry_type_str}, P_win: {opportunity.get('win_rate_pct')}%, E[R]: {opportunity.get('expected_value_r'):+.2f}R)："
                                        f"买入 {shares} 股，预计名义金额 ${sizing['notional']:,.0f}，占当前实时 Buying Power "
                                        f"(${sizing['available_buying_power']:,.2f}) 的 {sizing['buying_power_fraction']*100:.0f}%，硬止损 {sizing['stop_pct']*100:.2f}%。"
                                    )
                                    order_res = self.adapter.submit_market_order(ticker, shares, "buy", client_order_id=client_order_id)
                                    if order_res.get("success"):
                                        cycle_new_entries += 1
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
                                        self.entry_times.pop(ticker, None)
                                        self.add_log(f"❌ [{ticker}] BUY order failed. Reason: {order_res.get('error')}")

                            elif action == "SHORT" and current_shares == 0:
                                if not is_open:
                                    self.add_log(f"🌙 [盘后研判/休市记录] [{ticker}] 触发 SHORT 做空信号 (AI Score: {live_score}分, P_win: {opportunity.get('win_rate_pct')}%) | 非盘中时段，仅保留研判日志。")
                                else:
                                    account = self.adapter.get_account_summary()
                                    full_score_target = self._safe_float(self.strategy_params.get("full_size_score"), 75.0)
                                    is_probe = live_score < full_score_target
                                    sizing = self._size_probe_entry(account, close_price, opportunity) if is_probe else self._size_aggressive_entry(account, close_price, opportunity)
                                    shares = sizing["shares"]
                                    if shares <= 0:
                                        self.add_log(f"⚠️ [{ticker}] buying power 不足以卖空 1 股，跳过本次信号。")
                                        continue

                                    client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}-ENTRY"
                                    self.lock_entry(ticker)
                                    self.entry_times[ticker] = datetime.datetime.now()

                                    entry_type_str = "🧪 PROBE STARTER (25% 试探建仓)" if is_probe else "📉 FULL SIZE (大仓位进场)"
                                    self.add_log(
                                        f"📉 [{ticker}] SHORT {live_score:.1f}分 ({entry_type_str}, P_win: {opportunity.get('win_rate_pct')}%, E[R]: {opportunity.get('expected_value_r'):+.2f}R)："
                                        f"卖空 {shares} 股，预计名义金额 ${sizing['notional']:,.0f}，占当前实时 Buying Power "
                                        f"(${sizing['available_buying_power']:,.2f}) 的 {sizing['buying_power_fraction']*100:.0f}%，硬止损 {sizing['stop_pct']*100:.2f}%。"
                                    )
                                    order_res = self.adapter.submit_market_order(ticker, shares, "sell", client_order_id=client_order_id)
                                    if order_res.get("success"):
                                        cycle_new_entries += 1
                                        self.add_log(f"✅ [{ticker}] SHORT order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                        self.add_trade_action(
                                            "SHORT", ticker, shares, close_price, reason,
                                            order_id=order_res.get("order_id") or order_res.get("id"),
                                            client_order_id=client_order_id,
                                            order_status=order_res.get("status") or "submitted",
                                        )
                                    else:
                                        self.unlock_entry(ticker)
                                        self.entry_times.pop(ticker, None)
                                        self.add_log(f"❌ [{ticker}] SHORT order failed. Reason: {order_res.get('error')}")

                            elif action == "SELL" and current_shares > 0:
                                pnl = (close_price - avg_cost) * current_shares
                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}-EXIT"
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
                                    self.last_exit_times[ticker] = time.time()
                                    self.entry_times.pop(ticker, None)
                                    self.position_extremes.pop(ticker, None)
                                else:
                                    self.unlock_exit(ticker)
                                    self.add_log(f"❌ [{ticker}] SELL order failed. Reason: {order_res.get('error')}")

                            elif action == "COVER" and current_shares < 0:
                                cover_qty = abs(current_shares)
                                pnl = (avg_cost - close_price) * cover_qty
                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}-EXIT"
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
                                    self.last_exit_times[ticker] = time.time()
                                    self.entry_times.pop(ticker, None)
                                    self.position_extremes.pop(ticker, None)
                                else:
                                    self.unlock_exit(ticker)
                                    self.add_log(f"❌ [{ticker}] COVER order failed. Reason: {order_res.get('error')}")

                            elif action == "PARTIAL_SELL" and current_shares > 0:
                                sell_qty = max(1, current_shares // 2)
                                pnl = (close_price - avg_cost) * sell_qty
                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}-PARTIAL"
                                self.lock_exit(ticker)
                                self.add_log(f"🟢 [{ticker}] PARTIAL_SELL 触发分批止盈！市价平半仓 {sell_qty} 股 (预估锁利 ${pnl:.2f})...")
                                order_res = self.adapter.submit_market_order(ticker, sell_qty, "sell", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.partial_tp_done[ticker] = True
                                    self.add_log(f"✅ [{ticker}] PARTIAL_SELL 订单已提交！ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.add_trade_action(
                                        "PARTIAL_SELL", ticker, sell_qty, close_price, reason, pnl=pnl,
                                        order_id=order_res.get("order_id") or order_res.get("id"),
                                        client_order_id=client_order_id,
                                        order_status=order_res.get("status") or "submitted",
                                    )
                                else:
                                    self.unlock_exit(ticker)
                                    self.add_log(f"❌ [{ticker}] PARTIAL_SELL 订单失败. 原因: {order_res.get('error')}")

                            elif action == "PARTIAL_COVER" and current_shares < 0:
                                cover_qty = max(1, abs(current_shares) // 2)
                                pnl = (avg_cost - close_price) * cover_qty
                                client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}-PARTIAL"
                                self.lock_exit(ticker)
                                self.add_log(f"🟢 [{ticker}] PARTIAL_COVER 触发分批止盈！市价买回半仓 {cover_qty} 股 (预估锁利 ${pnl:.2f})...")
                                order_res = self.adapter.submit_market_order(ticker, cover_qty, "buy", client_order_id=client_order_id)
                                if order_res.get("success"):
                                    self.partial_tp_done[ticker] = True
                                    self.add_log(f"✅ [{ticker}] PARTIAL_COVER 订单已提交！ID: {order_res.get('order_id', order_res.get('id'))}")
                                    self.add_trade_action(
                                        "PARTIAL_COVER", ticker, cover_qty, close_price, reason, pnl=pnl,
                                        order_id=order_res.get("order_id") or order_res.get("id"),
                                        client_order_id=client_order_id,
                                        order_status=order_res.get("status") or "submitted",
                                    )
                                else:
                                    self.unlock_exit(ticker)
                                    self.add_log(f"❌ [{ticker}] PARTIAL_COVER 订单失败. 原因: {order_res.get('error')}")

                            elif action == "PYRAMID_BUY" and current_shares > 0:
                                # Pyramiding Buy (浮盈加仓): Add to a profitable long position
                                if not is_open:
                                    self.add_log(f"🌙 [盘后研判] [{ticker}] 浮盈加仓信号 (PYRAMID_BUY) | 非盘中，仅研判记录。")
                                elif self.is_entry_locked(ticker):
                                    self.add_log(f"⏳ [{ticker}] 浮盈加仓跳过：订单锁定中 (避免重复)")
                                else:
                                    account = self.adapter.get_account_summary()
                                    pyr_sizing = self._size_pyramid_entry(account, close_price, opportunity)
                                    pyr_shares = pyr_sizing["shares"]
                                    if pyr_shares <= 0:
                                        self.add_log(f"⚠️ [{ticker}] Buying power 不足以执行浮盈加仓，跳过。")
                                    else:
                                        pnl_float = (close_price - avg_cost) / avg_cost * 100.0 if avg_cost > 0 else 0.0
                                        client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}-PYRAMID"
                                        self.lock_entry(ticker)
                                        self.add_log(
                                            f"📈 [{ticker}] 浮盈加仓 PYRAMID_BUY! 当前浮盈 +{pnl_float:.2f}% — 追加 {pyr_shares} 股 @ ${close_price:.2f}，"
                                            f"名义 ${pyr_sizing['notional']:,.0f} | Score={live_score:.0f} E[R]={opportunity.get('expected_value_r', 0):+.2f}R"
                                        )
                                        order_res = self.adapter.submit_market_order(ticker, pyr_shares, "buy", client_order_id=client_order_id)
                                        if order_res.get("success"):
                                            self.pyramid_done[ticker] = True
                                            self.add_log(f"✅ [{ticker}] PYRAMID_BUY order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                            self.add_trade_action(
                                                "PYRAMID_BUY", ticker, pyr_shares, close_price, reason,
                                                order_id=order_res.get("order_id") or order_res.get("id"),
                                                client_order_id=client_order_id,
                                                order_status=order_res.get("status") or "submitted",
                                            )
                                        else:
                                            self.unlock_entry(ticker)
                                            self.add_log(f"❌ [{ticker}] PYRAMID_BUY order failed. Reason: {order_res.get('error')}")

                            elif action == "PYRAMID_SHORT" and current_shares < 0:
                                # Pyramiding Short (浮盈加空): Add to a profitable short position
                                if not is_open:
                                    self.add_log(f"🌙 [盘后研判] [{ticker}] 浮盈加空信号 (PYRAMID_SHORT) | 非盘中，仅研判记录。")
                                elif self.is_entry_locked(ticker):
                                    self.add_log(f"⏳ [{ticker}] 浮盈加空跳过：订单锁定中 (避免重复)")
                                else:
                                    account = self.adapter.get_account_summary()
                                    pyr_sizing = self._size_pyramid_entry(account, close_price, opportunity)
                                    pyr_shares = pyr_sizing["shares"]
                                    if pyr_shares <= 0:
                                        self.add_log(f"⚠️ [{ticker}] Buying power 不足以执行浮盈加空，跳过。")
                                    else:
                                        pnl_float = (avg_cost - close_price) / avg_cost * 100.0 if avg_cost > 0 else 0.0
                                        client_order_id = f"{ticker}-{int(datetime.datetime.now().timestamp())}-{uuid.uuid4().hex[:8]}-PYRAMID"
                                        self.lock_entry(ticker)
                                        self.add_log(
                                            f"📉 [{ticker}] 浮盈加空 PYRAMID_SHORT! 当前浮盈 +{pnl_float:.2f}% — 追加卖空 {pyr_shares} 股 @ ${close_price:.2f}，"
                                            f"名义 ${pyr_sizing['notional']:,.0f} | Score={live_score:.0f} E[R]={opportunity.get('expected_value_r', 0):+.2f}R"
                                        )
                                        order_res = self.adapter.submit_market_order(ticker, pyr_shares, "sell", client_order_id=client_order_id)
                                        if order_res.get("success"):
                                            self.pyramid_done[ticker] = True
                                            self.add_log(f"✅ [{ticker}] PYRAMID_SHORT order submitted! Order ID: {order_res.get('order_id', order_res.get('id'))}")
                                            self.add_trade_action(
                                                "SHORT", ticker, pyr_shares, close_price, reason,
                                                order_id=order_res.get("order_id") or order_res.get("id"),
                                                client_order_id=client_order_id,
                                                order_status=order_res.get("status") or "submitted",
                                            )
                                        else:
                                            self.unlock_entry(ticker)
                                            self.add_log(f"❌ [{ticker}] PYRAMID_SHORT order failed. Reason: {order_res.get('error')}")
                                    
                        except Exception as ex:
                            self.add_log(f"⚠️ Error scanning {ticker}: {str(ex)}")

                    self._score_warmup_complete = True

                    # EOD HuggingFace Auto-Sync: Runs once at market close (16:01 - 16:05 EST)
                    now_time = datetime.datetime.now().time()
                    if datetime.time(16, 1) <= now_time <= datetime.time(16, 5) and not getattr(self, "_eod_hf_synced_today", False):
                        self._eod_hf_synced_today = True
                        threading.Thread(target=self.sync_to_huggingface, daemon=True).start()

                loop_delay = 5 if is_market_opening_window else 30
                await asyncio.sleep(loop_delay)

            except asyncio.CancelledError:
                self.add_log("Background trading loop task cancelled.")
                break
            except Exception as e:
                self.add_log(f"⚠️ Main loop exception: {str(e)}")
                await asyncio.sleep(30)

    def sync_to_huggingface(self) -> Dict:
        """Uploads full master trade_history.json and daily partitions to HuggingFace Dataset repository (Ypeng12/quant-ai-trade-history)."""
        try:
            from data.sync_full_history_to_hf import sync_full_history_to_hf
            self.add_log("☁️ [HF Auto-Sync] 正在全量推送到 HuggingFace Dataset (Ypeng12/quant-ai-trade-history)...")
            sync_full_history_to_hf()
            self.add_log("✅ [HF Auto-Sync] 远端 HuggingFace 数据集同步成功！")
            return {"success": True, "message": "Synced to HuggingFace Dataset (Ypeng12/quant-ai-trade-history)"}
        except Exception as e:
            err_msg = f"⚠️ [HF Auto-Sync Error] {str(e)}"
            self.add_log(err_msg)
            return {"success": False, "error": str(e)}
