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

# 热门板块分类库 (Hot Sectors Universe)
HOT_SECTORS = {
    "AI_CHIPS": {
        "name": "🔥 AI & 半导体算力",
        "description": "人工智能芯片、算力服务器与晶圆代工龙头",
        "tickers": ["NVDA", "AMD", "AVGO", "TSM", "SMCI"]
    },
    "MEMORY_STORAGE": {
        "name": "💾 存储芯片 & AI 存储",
        "description": "DRAM/NAND/HBM 存储巨头与企业级 AI 存储基础设施",
        "tickers": ["MU", "WDC", "STX", "PSTG", "NTAP"]
    },
    "AI_POWER_NUCLEAR": {
        "name": "⚛️ AI 核能 & 电力基础设施",
        "description": "AI数据中心核电、清洁能源与电力基础设施龙头",
        "tickers": ["OKLO", "SMR", "VST", "CEG", "TLN"]
    },
    "QUANTUM_FRONTIER": {
        "name": "🔮 量子计算 & AI 软件",
        "description": "量子计算、大数据分析与高贝塔前沿科技",
        "tickers": ["PLTR", "IONQ", "RGTI"]
    },
    "BIG_TECH": {
        "name": "🏛️ 科技巨头 / 核心持仓",
        "description": "高流动性大盘科技股与核心资产",
        "tickers": ["TSLA", "AAPL", "MSFT", "META", "GOOGL"]
    },
    "MOMENTUM_CRYPTO": {
        "name": "🚀 高动能 & 加密概念",
        "description": "极高贝塔系数、强成交量与加密资产概念股",
        "tickers": ["MSTR", "COIN", "HOOD", "MARA", "TQQQ"]
    }
}

# 默认监控的精简核心股票池（方便用户自主添加与自定义）
WATCHLIST = ["NVDA", "TSLA", "AAPL", "AMD", "MU", "PLTR", "MSTR"]

# 三大 AI 操盘手模式配置与多因子权重 (AI Stock Trading Profiles)
TRADING_PROFILES = {
    "INTRADAY_HIGH_FREQ_SNIPER": {
        "id": "INTRADAY_HIGH_FREQ_SNIPER",
        "name": "🔥 INTRADAY_HIGH_FREQ_SNIPER (激进高频日内操盘手 - 默认)",
        "description": "极高交易频次，扫描 1 分钟 K 线，高动能突破，多因子权重：动能(45%), 成交量(35%), 波动率(15%), RSI(5%)",
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
        "name": "🎯 INTRADAY_DAILY_TARGET_500 ($500 目标日内止盈收工手)",
        "description": "每日止盈目标 $500，达成立即清仓，最大日亏 $300，15:55 强平不持股过夜，多因子权重：动能(35%), 成交量(30%), 波动率(25%), RSI(10%)",
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
        "name": "🧠 OPTIONS_QUANT_TRADER (大数据/ML 期权操盘手)",
        "description": "0DTE/7DTE 期权策略，积极监控 IV Rank 与 Skew 偏斜，大数据/ML 量化打分，高杠杆 Delta/Gamma 对冲",
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
