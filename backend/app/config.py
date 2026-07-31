# backend/app/config.py
import os
from dotenv import load_dotenv

# Load env variables from backend/.env
current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(os.path.dirname(current_dir), '.env')
load_dotenv(dotenv_path)

# Alpaca API 配置 (提供默认 Paper API Key，支持 Cloud/Docker 环境直接读取)
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "PKCY2OTNE7OHNTT65O47BSRIJS")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_API_SECRET") or "AXCEiytTK1rBgJZFAjNKPEpUy49KqYukP1H79DUtxz21"
ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# 模拟账户初始资金
INITIAL_CASH = 30000.0          # 初始本金：3万美金
DAILY_PROFIT_TARGET = 500.0     # 每日止盈目标：500刀，达到立刻强制平仓收工
DAILY_LOSS_LIMIT = 300.0        # 每日最大亏损额度：300刀，达到强制平仓收工防爆仓

# 单笔交易风险控制
RISK_PER_TRADE_PCT = 0.01       # 单笔交易最大允许亏损：总本金的 1% ($300)
MAX_POSITION_SIZE_PCT = 0.50     # 单只股票最大持仓比例：不超过账户总资产的 50%

# 账户级高级风控
SOFT_DRAWDOWN_LIMIT = 0.07       # 软回撤降险线：自权益高峰回撤达 7%，单笔交易风险减半
HARD_DRAWDOWN_LIMIT = 0.12       # 硬回撤熔断线：自权益高峰回撤达 12%，停止新开仓
MAX_CONSECUTIVE_LOSSES = 5       # 连续亏损上限：连亏 5 笔触发降险，单笔交易风险减半


# 真实交易损耗模拟 (防守佣金与滑点)
SLIPPAGE_RATE = 0.0003          # 滑点率：万分之三（买入加价 0.03%，卖出减价 0.03%）
COMMISSION_PER_SHARE = 0.005    # 每股交易佣金：0.005 美元
MIN_COMMISSION_PER_ORDER = 1.0  # 单笔交易最低收取佣金：1.0 美元 (即使只买1股也收1刀，惩罚频繁极小单交易)

# 交易时间控制 (美东时间 EST)
MARKET_OPEN_TIME = "09:30"
MARKET_CLOSE_TIME = "16:00"
FORCE_LIQUIDATION_TIME = "15:55" # 日内清仓时间：下午 3:55 强制无条件市价清仓，不持股过夜

# 开盘突击模式配置
MARKET_OPEN_FOCUS_DEFAULT = True  # 是否默认开启开盘突击模式
MARKET_OPEN_FOCUS_START = "09:30" # 开盘开始时间
MARKET_OPEN_FOCUS_END = "10:15"   # 开盘结束时间 (前 45 分钟)
FORCE_LIQUIDATION_OPEN_FOCUS = "10:30" # 开盘突击模式下，10:30 强制清仓出场，防午盘横盘震荡损耗

# Hot Sectors Universe
HOT_SECTORS = {
    "AI_CHIPS": {
        "name": "🔥 AI & Semiconductor Chips",
        "description": "AI accelerators, GPU servers, and semiconductor wafer foundries",
        "tickers": ["NVDA", "AMD", "AVGO", "TSM", "SMCI"]
    },
    "MEMORY_STORAGE": {
        "name": "💾 Memory & AI Storage",
        "description": "DRAM/NAND/HBM storage leaders and enterprise AI storage infrastructure",
        "tickers": ["MU", "WDC", "STX", "PSTG", "NTAP"]
    },
    "AI_POWER_NUCLEAR": {
        "name": "⚛️ AI Nuclear & Power Infrastructure",
        "description": "Nuclear power, clean energy, and power grid leaders for AI data centers",
        "tickers": ["OKLO", "SMR", "VST", "CEG", "TLN"]
    },
    "QUANTUM_FRONTIER": {
        "name": "🔮 Quantum Computing & AI Software",
        "description": "Quantum computing, big data analytics, and high-beta tech pioneers",
        "tickers": ["PLTR", "IONQ", "RGTI"]
    },
    "BIG_TECH": {
        "name": "🏛️ Mega-Cap Tech / Core Holdings",
        "description": "High-liquidity mega-cap technology leaders and core holdings",
        "tickers": ["TSLA", "AAPL", "MSFT", "META", "GOOGL"]
    },
    "MOMENTUM_CRYPTO": {
        "name": "🚀 High Momentum & Crypto Concepts",
        "description": "High beta, volume breakout, and crypto-related growth assets",
        "tickers": ["MSTR", "COIN", "HOOD", "MARA", "TQQQ"]
    }
}

# =========================================================================
# 🎯 WATCHLIST & AI AGENT UNIVERSE ARCHITECTURE
# -------------------------------------------------------------------------
# 1. Single Source of Truth: Alpaca's Official Cloud Watchlist (PRIMARY_QUANT)
#    is the SOLE universe monitored, analyzed, and traded by the AI Bot.
# 2. Synchronized User Control: Any add, delete, clear, or preset action in UI
#    instantly updates Alpaca Cloud Watchlist via REST API.
# 3. Strategy Mode Presets: Different trading profiles (Sniper, Momentum, Tech)
#    can recommend specialized stock pools that fill directly into Watchlist.
# -------------------------------------------------------------------------
# TODO: Future AI Stock Selector Module (AI Agent Screener)
# In future releases, an autonomous AI Stock Selector agent will scan the US
# market (RVOL, Gap %, Sentiment, Technical Breakouts, News Catalyst) and
# dynamically recommend & inject high-beta tickers into Alpaca's Watchlist!
# =========================================================================

# Persistent Watchlist File Path (backend/watchlist.json)
WATCHLIST_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "watchlist.json")
DEFAULT_WATCHLIST = ["NVDA", "PLTR", "SNDK", "CRCL", "TSLA", "AMD"]

def load_watchlist() -> list:
    """拉取 Watchlist 优先级: 1) Alpaca 官方云端 Watchlist -> 2) 本地 watchlist.json -> 3) 默认 8 支股票"""
    import json
    try:
        from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY
        if ALPACA_API_KEY and "your_paper_api_key_here" not in ALPACA_API_KEY:
            from alpaca.trading.client import TradingClient
            client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
            watchlists = client.get_watchlists()
            if watchlists:
                qw = next((w for w in watchlists if w.name == "PRIMARY_QUANT"), watchlists[0])
                if qw is not None:
                    alpaca_symbols = [str(a.symbol).upper().strip() for a in (qw.assets or []) if getattr(a, "symbol", None)]
                    try:
                        with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
                            json.dump(alpaca_symbols, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    return alpaca_symbols
    except Exception as e:
        print(f"Alpaca cloud watchlist fetch warning: {e}")

    try:
        if os.path.exists(WATCHLIST_FILE):
            with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [str(t).upper().strip() for t in data if t]
    except Exception as e:
        print(f"Error loading watchlist.json: {e}")
    return DEFAULT_WATCHLIST.copy()


def save_watchlist(tickers: list, allow_empty: bool = True) -> list:
    """同步保存 Watchlist 到本地磁盘 watchlist.json 并且 100% 双向实时同步到 Alpaca 官方云端 Watchlist。"""
    import json
    cleaned = []
    for t in tickers:
        if t and isinstance(t, str):
            sym = t.upper().strip()
            if sym and sym not in cleaned:
                cleaned.append(sym)

    if not cleaned and not allow_empty:
        cleaned = DEFAULT_WATCHLIST.copy()

    # 1. 保存到本地磁盘
    try:
        with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(cleaned, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving watchlist.json: {e}")

    # 2. 100% 双向实时同步到 Alpaca 官方云端账户
    try:
        from app.config import ALPACA_API_KEY, ALPACA_SECRET_KEY
        if ALPACA_API_KEY and "your_paper_api_key_here" not in ALPACA_API_KEY:
            from alpaca.trading.client import TradingClient
            from alpaca.trading.requests import CreateWatchlistRequest, UpdateWatchlistRequest
            client = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
            watchlists = client.get_watchlists()
            qw = next((w for w in watchlists if w.name == "PRIMARY_QUANT"), None)
            if qw:
                req = UpdateWatchlistRequest(name="PRIMARY_QUANT", symbols=cleaned)
                client.update_watchlist_by_id(qw.id, req)
            else:
                req = CreateWatchlistRequest(name="PRIMARY_QUANT", symbols=cleaned)
                client.create_watchlist(req)
    except Exception as e:
        print(f"Sync Alpaca cloud watchlist error: {e}")

    return cleaned

# Default monitored core watchlist (loaded from disk)
WATCHLIST = load_watchlist()


# Three Core AI Trader Profiles & Multi-Factor Weights
TRADING_PROFILES = {
    "INTRADAY_HIGH_FREQ_SNIPER": {
        "id": "INTRADAY_HIGH_FREQ_SNIPER",
        "name": "🔥 INTRADAY_HIGH_FREQ_SNIPER (Aggressive High-Frequency Sniper - Default)",
        "description": "High frequency 1-min K-line scanning, high-momentum breakout. Factor weights: Momentum (45%), Volume (35%), Volatility (15%), RSI (5%)",
        "is_default": True,
        "weights": {
            "momentum": 0.45,
            "volume": 0.35,
            "volatility": 0.15,
            "rsi": 0.05
        },
        "params": {
            "strategy_mode": "opening_breakout",
            "rsi_threshold_buy": 75.0,
            "rvol_min": 1.1,
            "stop_loss_pct": 0.010,
            "profit_target_pct": 0.020,
            "trailing_stop_atr_mult": 1.5,
            "scan_interval": "1m"
        }
    },
    "INTRADAY_DAILY_TARGET_500": {
        "id": "INTRADAY_DAILY_TARGET_500",
        "name": "🎯 INTRADAY_DAILY_TARGET_500 ($500 Daily Profit Target Trader)",
        "description": "Daily profit target $500 lock, max daily loss $300, 15:55 EOD liquidation without overnight risk. Factor weights: Momentum (35%), Volume (30%), Volatility (25%), RSI (10%)",
        "is_default": False,
        "weights": {
            "momentum": 0.35,
            "volume": 0.30,
            "volatility": 0.25,
            "rsi": 0.10
        },
        "params": {
            "strategy_mode": "dynamic",
            "daily_profit_target": 500.0,
            "daily_loss_limit": 300.0,
            "stop_loss_pct": 0.012,
            "profit_target_pct": 0.018,
            "force_liquidation_time": "15:55",
            "scan_interval": "5m"
        }
    },
    "OPTIONS_QUANT_TRADER": {
        "id": "OPTIONS_QUANT_TRADER",
        "name": "🧠 OPTIONS_QUANT_TRADER (Options Quant & Volatility Trader)",
        "description": "0DTE/7DTE options strategies monitoring IV Rank & Skew, ML quantitative scoring, leverage Delta/Gamma hedging",
        "is_default": False,
        "weights": {
            "iv_rank": 0.40,
            "momentum": 0.30,
            "skew": 0.20,
            "delta_gamma": 0.10
        },
        "params": {
            "strategy_mode": "options_quant",
            "rsi_threshold_buy": 70.0,
            "iv_rank_min": 30.0,
            "max_option_spend_per_trade": 1000.0,
            "stop_loss_pct": 0.025,
            "profit_target_pct": 0.050,
            "scan_interval": "1m"
        }
    }
}
