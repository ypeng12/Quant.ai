# backend/app/agent.py
"""
AI Agent Core Module — Natural Language → Strategy Config
Supports OpenAI-compatible APIs and Gemini API. Falls back to template-based parsing when no API key is available.
"""

import json
import os
import re
from app.llm_client import chat_completion, get_usage_stats

# Default strategy config template
DEFAULT_STRATEGY_CONFIG = {
    "ticker": "TSLA",
    "interval": "1d",
    "strategy_mode": "dynamic",
    "stop_loss_pct": 0.015,
    "profit_target_pct": 0.030,
    "trailing_stop_mode": "atr",
    "trailing_stop_atr_mult": 2.0,
    "rsi_threshold_buy": 65.0,
    "risk_per_trade_pct": 0.01,
    "max_position_size_pct": 0.50,
    "position_sizing_mode": "atr",
    "commission_per_share": 0.005,
    "slippage_rate": 0.0003
}

# Mapping of common natural language terms → strategy parameters
TICKER_ALIASES = {
    "tesla": "TSLA", "tsla": "TSLA",
    "nvidia": "NVDA", "nvda": "NVDA",
    "apple": "AAPL", "aapl": "AAPL",
    "microsoft": "MSFT", "msft": "MSFT",
    "amd": "AMD",
    "google": "GOOGL", "googl": "GOOGL", "alphabet": "GOOGL",
    "amazon": "AMZN", "amzn": "AMZN",
    "meta": "META", "facebook": "META",
    "spy": "SPY", "qqq": "QQQ",
}

STRATEGY_ALIASES = {
    "donchian": "dynamic", "breakout": "breakout", "突破": "breakout",
    "ema": "ema_cross", "均线": "ema_cross", "金叉": "ema_cross",
    "pattern": "patterns", "形态": "patterns", "k线": "patterns",
    "consensus": "consensus", "共振": "consensus",
    "dynamic": "dynamic", "动态": "dynamic", "自适应": "dynamic",
    "mean reversion": "dynamic", "均值回归": "dynamic",
    "trend": "dynamic", "趋势": "dynamic",
}

INTERVAL_ALIASES = {
    "1分钟": "1m", "1min": "1m", "1minute": "1m", "1m": "1m",
    "5分钟": "5m", "5min": "5m", "5minute": "5m", "5m": "5m",
    "15分钟": "15m", "15min": "15m", "15m": "15m",
    "30分钟": "30m", "30min": "30m", "30m": "30m",
    "1小时": "1h", "1hour": "1h", "1h": "1h", "hourly": "1h",
    "日线": "1d", "daily": "1d", "1d": "1d", "1day": "1d",
    "day": "1d", "天": "1d",
}

# Available backend tools (for LLM function calling)
BACKEND_TOOLS = [
    {
        "name": "fetch_market_data",
        "description": "Fetch historical OHLCV market data for a given ticker and time range",
        "parameters": {"ticker": "str", "period": "str", "interval": "str"}
    },
    {
        "name": "compute_indicators",
        "description": "Compute technical indicators (EMA, RSI, ATR, MACD, ADX, Bollinger Bands, etc.) on market data",
        "parameters": {"ticker": "str", "interval": "str"}
    },
    {
        "name": "run_backtest",
        "description": "Run a backtest simulation with given strategy and risk parameters",
        "parameters": {"strategy_config": "dict"}
    },
    {
        "name": "generate_risk_report",
        "description": "Generate AI risk analysis report from backtest results",
        "parameters": {"backtest_id": "str"}
    }
]

EXAMPLE_PROMPTS = [
    "Backtest TSLA with Donchian breakout strategy over the past year using daily bars",
    "Test NVDA with EMA crossover strategy on 5-minute bars, use 1.5x ATR trailing stop",
    "Run a mean reversion backtest on SPY with RSI oversold at 10 and Bollinger Bands",
    "Compare dynamic routing vs consensus strategy on AAPL daily data",
    "用日线级别回测 MSFT 的动态路由策略，ATR 止损倍数设为 2.5"
]

SYSTEM_PROMPT = """You are the AI Strategy Parser engine for Quant.ai. 
Your task is to analyze the user's trading strategy description in natural language and extract a precise, valid strategy configuration in JSON format.

You must output a JSON object containing the following keys (you can leave out keys to use defaults, but you must ensure any provided keys have valid types and ranges):
- ticker (string, uppercase, e.g., "TSLA")
- interval (string, e.g., "1m", "5m", "15m", "30m", "1h", "1d")
- strategy_mode (string, choice of: "dynamic", "ema_cross", "breakout", "patterns", "consensus")
- stop_loss_pct (float, range 0.001 to 0.20, e.g., 0.015)
- profit_target_pct (float, range 0.001 to 0.50, e.g., 0.030)
- trailing_stop_mode (string, choice of: "atr", "fixed", "none")
- trailing_stop_atr_mult (float, range 0.5 to 5.0, e.g., 2.0)
- rsi_threshold_buy (float, range 10.0 to 90.0, e.g., 65.0)
- risk_per_trade_pct (float, range 0.001 to 0.10, e.g., 0.01)
- max_position_size_pct (float, range 0.05 to 1.00, e.g., 0.50)
- position_sizing_mode (string, choice of: "atr", "fixed")
- commission_per_share (float, range 0.0 to 0.10, e.g., 0.005)
- slippage_rate (float, range 0.0 to 0.01, e.g., 0.0003)

If the user wants a SMA or EMA cross strategy, set strategy_mode to "ema_cross".
If the user wants candle patterns, breakout, consensus, etc., set strategy_mode to "patterns", "breakout", "consensus" or "dynamic".
If the user's description is vague, merge your extractions with the default config:
{default_config}

CRITICAL: Return ONLY a valid JSON block enclosed in ```json ... ``` code blocks. Do not add conversational text around it when generating strategy_config.
"""

CHAT_SYSTEM_PROMPT = """You are Quant.ai's Quantitative Research Assistant.
You help users design, refine, and backtest quantitative trading strategies.
When the user describes a trading strategy or asks questions:
1. Provide a professional, helpful, and natural language explanation/response.
2. If the user's message contains a trading strategy or a change to an existing strategy, you MUST ALSO generate a JSON strategy configuration block inside ```json ... ```.
   The JSON config must match the following format and merge with the current config:
   {default_config}
   
Valid fields:
- ticker (string, uppercase)
- interval ("1m", "5m", "15m", "30m", "1h", "1d")
- strategy_mode ("dynamic", "ema_cross", "breakout", "patterns", "consensus")
- stop_loss_pct (float, 0.001-0.20)
- profit_target_pct (float, 0.001-0.50)
- trailing_stop_mode ("atr", "fixed", "none")
- trailing_stop_atr_mult (float, 0.5-5.0)
- rsi_threshold_buy (float, 10-90)
- risk_per_trade_pct (float, 0.001-0.10)
- max_position_size_pct (float, 0.05-1.00)
- position_sizing_mode ("atr", "fixed")
- commission_per_share (float)
- slippage_rate (float)

Response format:
Write your professional suggestions or chat response, followed by the ```json ... ``` block containing the extracted strategy_config (only if a strategy description is present).
"""

def parse_research_prompt(prompt: str, use_llm: bool = True) -> dict:
    """
    Parse a natural language research prompt into a strategy_config JSON.
    First tries LLM parsing if use_llm is True and keys exist, otherwise falls back to template.
    """
    if use_llm:
        openai_key = os.environ.get("OPENAI_API_KEY")
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if openai_key or gemini_key:
            res = parse_with_llm(prompt)
            if res:
                return res

    # Fallback template parsing
    prompt_lower = prompt.lower().strip()
    config = DEFAULT_STRATEGY_CONFIG.copy()
    parsed_parts = []
    
    # 1. Extract ticker
    ticker_found = False
    for alias, ticker in TICKER_ALIASES.items():
        if alias in prompt_lower:
            config["ticker"] = ticker
            parsed_parts.append(f"Ticker: {ticker}")
            ticker_found = True
            break
    
    if not ticker_found:
        ticker_match = re.findall(r'\b([A-Z]{1,5})\b', prompt)
        if ticker_match:
            config["ticker"] = ticker_match[0]
            parsed_parts.append(f"Ticker: {ticker_match[0]}")
    
    # 2. Extract strategy mode
    for alias, mode in STRATEGY_ALIASES.items():
        if alias in prompt_lower:
            config["strategy_mode"] = mode
            parsed_parts.append(f"Strategy: {mode}")
            break
    
    # 3. Extract interval
    for alias, interval in INTERVAL_ALIASES.items():
        if alias in prompt_lower:
            config["interval"] = interval
            parsed_parts.append(f"Interval: {interval}")
            break
    
    # 4. Extract ATR multiplier
    atr_match = re.search(r'atr.*?(\d+\.?\d*)', prompt_lower)
    if atr_match:
        atr_val = float(atr_match.group(1))
        if 0.5 <= atr_val <= 5.0:
            config["trailing_stop_atr_mult"] = atr_val
            parsed_parts.append(f"ATR Multiplier: {atr_val}")
    
    # 5. Extract RSI threshold
    rsi_match = re.search(r'rsi.*?(\d+)', prompt_lower)
    if rsi_match:
        rsi_val = float(rsi_match.group(1))
        if 5 <= rsi_val <= 90:
            config["rsi_threshold_buy"] = rsi_val
            parsed_parts.append(f"RSI Threshold: {rsi_val}")
    
    # 6. Extract risk percentage
    risk_match = re.search(r'risk.*?(\d+\.?\d*)%', prompt_lower)
    if risk_match:
        risk_val = float(risk_match.group(1)) / 100
        if 0.001 <= risk_val <= 0.05:
            config["risk_per_trade_pct"] = risk_val
            parsed_parts.append(f"Risk Per Trade: {risk_val*100}%")
    
    execution_plan = [
        {"step": 1, "tool": "fetch_market_data", "desc": f"Fetch {config['interval']} OHLCV data for {config['ticker']}"},
        {"step": 2, "tool": "compute_indicators", "desc": "Calculate technical indicators (EMA, RSI, ATR, MACD, ADX, Bollinger Bands, Donchian)"},
        {"step": 3, "tool": "run_backtest", "desc": f"Run {config['strategy_mode']} strategy backtest with ATR={config['trailing_stop_atr_mult']}x trailing stop"},
        {"step": 4, "tool": "generate_risk_report", "desc": "Analyze results: drawdown, regime performance, parameter sensitivity, overfitting risk"}
    ]
    
    parsed_intent = f"Backtest {config['ticker']} using {config['strategy_mode']} strategy on {config['interval']} bars"
    if parsed_parts:
        parsed_intent += f" (Parsed: {', '.join(parsed_parts)})"
    
    return {
        "strategy_config": config,
        "execution_plan": execution_plan,
        "parsed_intent": parsed_intent,
        "source": "template",
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
    }


def parse_with_llm(prompt: str, history: list = None) -> dict:
    """
    Call LLM to parse a natural language prompt into a strategy configuration.
    """
    sys_prompt = SYSTEM_PROMPT.format(default_config=json.dumps(DEFAULT_STRATEGY_CONFIG, indent=2))
    messages = [
        {"role": "system", "content": sys_prompt}
    ]
    if history:
        for h in history:
            messages.append(h)
    messages.append({"role": "user", "content": prompt})
    
    res = chat_completion(messages)
    if not res or not res.get("available"):
        return None
        
    content = res["content"]
    
    try:
        config_data = json.loads(content)
    except Exception:
        match = re.search(r'\{.*\}', content, re.DOTALL)
        if match:
            try:
                config_data = json.loads(match.group(0))
            except Exception:
                return None
        else:
            return None
            
    final_config = DEFAULT_STRATEGY_CONFIG.copy()
    
    for k, v in config_data.items():
        if k in DEFAULT_STRATEGY_CONFIG:
            try:
                if k == "ticker":
                    final_config[k] = str(v).upper()
                elif k == "interval" and str(v) in ["1m", "5m", "15m", "30m", "1h", "1d"]:
                    final_config[k] = str(v)
                elif k == "strategy_mode" and str(v) in ["dynamic", "ema_cross", "breakout", "patterns", "consensus"]:
                    final_config[k] = str(v)
                elif k == "stop_loss_pct":
                    final_config[k] = max(0.001, min(0.20, float(v)))
                elif k == "profit_target_pct":
                    final_config[k] = max(0.001, min(0.50, float(v)))
                elif k == "trailing_stop_mode" and str(v) in ["atr", "fixed", "none"]:
                    final_config[k] = str(v)
                elif k == "trailing_stop_atr_mult":
                    final_config[k] = max(0.5, min(5.0, float(v)))
                elif k == "rsi_threshold_buy":
                    final_config[k] = max(10.0, min(90.0, float(v)))
                elif k == "risk_per_trade_pct":
                    final_config[k] = max(0.001, min(0.10, float(v)))
                elif k == "max_position_size_pct":
                    final_config[k] = max(0.05, min(1.00, float(v)))
                elif k == "position_sizing_mode" and str(v) in ["atr", "fixed"]:
                    final_config[k] = str(v)
                elif k == "commission_per_share":
                    final_config[k] = max(0.0, min(0.10, float(v)))
                elif k == "slippage_rate":
                    final_config[k] = max(0.0, min(0.01, float(v)))
            except Exception:
                pass
                
    execution_plan = [
        {"step": 1, "tool": "fetch_market_data", "desc": f"Fetch {final_config['interval']} OHLCV data for {final_config['ticker']}"},
        {"step": 2, "tool": "compute_indicators", "desc": "Calculate technical indicators (EMA, RSI, ATR, MACD, ADX, Bollinger Bands, Donchian)"},
        {"step": 3, "tool": "run_backtest", "desc": f"Run {final_config['strategy_mode']} strategy backtest with ATR={final_config['trailing_stop_atr_mult']}x trailing stop"},
        {"step": 4, "tool": "generate_risk_report", "desc": "Analyze results: drawdown, regime performance, parameter sensitivity, overfitting risk"}
    ]
    
    parsed_intent = f"Backtest {final_config['ticker']} using {final_config['strategy_mode']} strategy on {final_config['interval']} bars"
    
    return {
        "strategy_config": final_config,
        "execution_plan": execution_plan,
        "parsed_intent": parsed_intent,
        "source": "llm",
        "usage": res["usage"]
    }


def get_chat_response(prompt: str, history: list = None) -> dict:
    """
    Generate chatbot strategy recommendations and natural language explanations.
    """
    sys_prompt = CHAT_SYSTEM_PROMPT.format(default_config=json.dumps(DEFAULT_STRATEGY_CONFIG, indent=2))
    messages = [
        {"role": "system", "content": sys_prompt}
    ]
    if history:
        for h in history:
            messages.append(h)
    messages.append({"role": "user", "content": prompt})
    
    res = chat_completion(messages)
    
    # Fallback to templates if LLM has no key
    if not res or not res.get("available"):
        parsed = parse_research_prompt(prompt, use_llm=False)
        msg = f"你好！我是 Quant.ai 策略研究助手。由于目前未检测到可用的大模型 API 密钥（OPENAI_API_KEY 或 GEMINI_API_KEY），我已使用系统规则模板将您的策略解析为：{parsed['parsed_intent']}。您可以在控制面板中查看详细参数并点击执行回测。"
        return {
            "message": msg,
            "strategy_config": parsed["strategy_config"],
            "execution_plan": parsed["execution_plan"],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost_usd": 0.0}
        }
        
    content = res["content"]
    strategy_config = None
    clean_msg = content
    
    # Try parsing json out
    match = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
    if not match:
        match = re.search(r'(\{.*?\})', content, re.DOTALL)
        
    if match:
        try:
            config_data = json.loads(match.group(1))
            strategy_config = DEFAULT_STRATEGY_CONFIG.copy()
            for k, v in config_data.items():
                if k in DEFAULT_STRATEGY_CONFIG:
                    try:
                        if k == "ticker":
                            strategy_config[k] = str(v).upper()
                        elif k == "interval" and str(v) in ["1m", "5m", "15m", "30m", "1h", "1d"]:
                            strategy_config[k] = str(v)
                        elif k == "strategy_mode" and str(v) in ["dynamic", "ema_cross", "breakout", "patterns", "consensus"]:
                            strategy_config[k] = str(v)
                        elif k == "stop_loss_pct":
                            strategy_config[k] = max(0.001, min(0.20, float(v)))
                        elif k == "profit_target_pct":
                            strategy_config[k] = max(0.001, min(0.50, float(v)))
                        elif k == "trailing_stop_mode" and str(v) in ["atr", "fixed", "none"]:
                            strategy_config[k] = str(v)
                        elif k == "trailing_stop_atr_mult":
                            strategy_config[k] = max(0.5, min(5.0, float(v)))
                        elif k == "rsi_threshold_buy":
                            strategy_config[k] = max(10.0, min(90.0, float(v)))
                        elif k == "risk_per_trade_pct":
                            strategy_config[k] = max(0.001, min(0.10, float(v)))
                        elif k == "max_position_size_pct":
                            strategy_config[k] = max(0.05, min(1.00, float(v)))
                        elif k == "position_sizing_mode" and str(v) in ["atr", "fixed"]:
                            strategy_config[k] = str(v)
                        elif k == "commission_per_share":
                            strategy_config[k] = max(0.0, min(0.10, float(v)))
                        elif k == "slippage_rate":
                            strategy_config[k] = max(0.0, min(0.01, float(v)))
                    except Exception:
                        pass
            
            clean_msg = content.replace(match.group(0), "").strip()
            if not clean_msg:
                clean_msg = f"我已为您生成了策略配置：{strategy_config['ticker']} ({strategy_config['strategy_mode']})。"
        except Exception:
            pass
            
    if not strategy_config:
        strategy_config = DEFAULT_STRATEGY_CONFIG.copy()
        
    execution_plan = [
        {"step": 1, "tool": "fetch_market_data", "desc": f"Fetch {strategy_config['interval']} OHLCV data for {strategy_config['ticker']}"},
        {"step": 2, "tool": "compute_indicators", "desc": "Calculate technical indicators (EMA, RSI, ATR, MACD, ADX, Bollinger Bands, Donchian)"},
        {"step": 3, "tool": "run_backtest", "desc": f"Run {strategy_config['strategy_mode']} strategy backtest with ATR={strategy_config['trailing_stop_atr_mult']}x trailing stop"},
        {"step": 4, "tool": "generate_risk_report", "desc": "Analyze results: drawdown, regime performance, parameter sensitivity, overfitting risk"}
    ]
    
    return {
        "message": clean_msg,
        "strategy_config": strategy_config,
        "execution_plan": execution_plan,
        "usage": res["usage"]
    }


def get_example_prompts() -> list:
    """Return example research prompts for the frontend"""
    return EXAMPLE_PROMPTS


def get_backend_tools() -> list:
    """Return available backend tools for documentation"""
    return BACKEND_TOOLS
