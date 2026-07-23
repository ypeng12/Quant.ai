# backend/app/config.py
import os
from dotenv import load_dotenv

# Load env variables from backend/.env
current_dir = os.path.dirname(os.path.abspath(__file__))
dotenv_path = os.path.join(os.path.dirname(current_dir), '.env')
load_dotenv(dotenv_path)

# Alpaca API 配置
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY") or os.getenv("ALPACA_API_SECRET")
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

# 默认监控的高流动性股票池
WATCHLIST = ["TSLA", "NVDA", "AAPL", "MSFT", "AMD"]
