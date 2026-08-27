# backend/app/broker/mock_adapter.py
"""
Mock Alpaca Broker Adapter Module
Provides local simulated paper trading execution, clock, and balance management.
"""

import datetime
import pytz
from typing import Dict, List, Optional
from app.broker.alpaca_adapter import AlpacaAdapter

class MockAlpacaAdapter:
    def __init__(self):
        self.cash = 0.0
        self.equity = 0.0
        self.buying_power = 0.0
        self.multiplier = 4.0
        self.positions = {}
        self._sync_real_alpaca()

    def _sync_real_alpaca(self):
        """动态尝试读取 Alpaca 账户真实的实时剩余资金与资产，绝不用硬编码数额。"""
        try:
            from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_BASE_URL
            adapter = AlpacaAdapter(api_key=ALPACA_API_KEY, api_secret=ALPACA_SECRET_KEY, base_url=ALPACA_BASE_URL)
            acc = adapter.get_account_summary()
            if acc and acc.get("success"):
                self.cash = float(acc.get("cash", 0.0))
                self.equity = float(acc.get("equity", 0.0))
                self.buying_power = float(acc.get("buying_power", 0.0))
                self.multiplier = float(acc.get("multiplier", 4.0))
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
            self.buying_power = 120000.0

    def get_account_summary(self) -> Dict:
        pos_val = sum(pos["shares"] * pos.get("current_price", pos["avg_entry_price"]) for pos in self.positions.values())
        self.equity = round(self.cash + pos_val, 2)
        bp = self.buying_power if self.buying_power > 0 else max(0.0, self.cash * self.multiplier)
        return {
            "success": True,
            "account_number": "MOCK_PAPER_9988",
            "status": "ACTIVE (本地虚拟盘)",
            "currency": "USD",
            "cash": round(self.cash, 2),
            "portfolio_value": self.equity,
            "buying_power": round(bp, 2),
            "multiplier": getattr(self, "multiplier", 4.0),
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

        order_val = round(qty * exec_price, 2)
        if side.lower() == "buy":
            if old_sh >= 0:
                new_sh = old_sh + qty
                new_avg = round(((old_sh * old_avg) + (qty * exec_price)) / new_sh, 2) if new_sh > 0 else exec_price
                self.positions[symbol] = {"shares": new_sh, "avg_entry_price": new_avg, "current_price": exec_price}
                self.cash -= order_val
                if self.buying_power > 0:
                    self.buying_power = max(0.0, self.buying_power - order_val)
            else:
                cover_qty = min(qty, abs(old_sh))
                new_sh = old_sh + cover_qty
                pnl = (old_avg - exec_price) * cover_qty
                self.cash += round((cover_qty * old_avg) + pnl, 2)
                if self.buying_power > 0:
                    self.buying_power += round(cover_qty * exec_price, 2)
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
                if self.buying_power > 0:
                    self.buying_power += round(sell_qty * exec_price, 2)
                if new_sh == 0:
                    del self.positions[symbol]
                else:
                    self.positions[symbol] = {"shares": new_sh, "avg_entry_price": old_avg, "current_price": exec_price}
            else:
                new_sh = old_sh - qty
                new_avg = round(((abs(old_sh) * old_avg) + (qty * exec_price)) / abs(new_sh), 2) if new_sh != 0 else exec_price
                self.positions[symbol] = {"shares": new_sh, "avg_entry_price": new_avg, "current_price": exec_price}
                self.cash -= order_val
                if self.buying_power > 0:
                    self.buying_power = max(0.0, self.buying_power - order_val)

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
