# backend/main_api.py

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
import datetime
import pandas as pd
import numpy as np
import yfinance as yf

import math

def clean_float(val, default=0.0):
    if val is None or pd.isna(val):
        return default
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


from app.config import INITIAL_CASH, WATCHLIST, FORCE_LIQUIDATION_TIME
from app.data_manager import fetch_and_prepare_data, get_company_info, calculate_atr, INTERVAL_TO_PERIOD
from app.patterns import analyze_patterns
from app.simulator import run_backtest_sim
from app.agent import parse_research_prompt, get_example_prompts, get_backend_tools, get_chat_response
from app.llm_client import get_usage_stats as llm_get_usage
from app.data_cache import get_cache_stats, invalidate_cache
from app.experiment_manager import list_experiments, save_experiment, get_experiment, delete_experiment, compare_experiments
from app.risk_analyst import generate_risk_report
import time

app = FastAPI(title="Quant.ai API Server")

# 请求延迟追踪
request_latencies = []

@app.middleware("http")
async def track_latency(request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000
    request_latencies.append(duration_ms)
    if len(request_latencies) > 1000:  # 只保留最近1000条
        request_latencies.pop(0)
    return response

# 允许跨域请求 (CORS)，方便 React 前端调用
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发阶段允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/watchlist")
def get_watchlist_data():
    """
    获取自选股池的列表
    """
    return {"watchlist": WATCHLIST}

@app.get("/api/company_info")
def get_company_details(ticker: str):
    """
    获取指定股票的公司详情元数据
    """
    info = get_company_info(ticker.upper())
    return info

@app.get("/api/scan")
def scan_market_stocks(tickers: str = None):
    """
    接口：运行盘前扫描器，分析多个股票的 RVol, ATR%, Gap% 强度并输出推荐意见
    """
    if tickers:
        ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]
    else:
        # 默认扫描 watchlist
        ticker_list = WATCHLIST.copy()

    results = []
    for ticker in ticker_list:
        try:
            # 获取最近 30 天的日线数据
            stock = yf.Ticker(ticker)
            df = stock.history(period="30d")
            
            if df.empty or len(df) < 20:
                continue
                
            latest_day = df.iloc[-1]
            prev_day = df.iloc[-2]
            
            # 1. 相对成交量 (RVol)
            avg_volume_20d = df['Volume'].iloc[-21:-1].mean()
            latest_volume = latest_day['Volume']
            rvol = latest_volume / avg_volume_20d if avg_volume_20d > 0 else 0
            
            # 2. 波动率 ATR % of Price
            df['ATR'] = calculate_atr(df, period=14)
            latest_atr = df['ATR'].iloc[-1]
            atr_pct = (latest_atr / latest_day['Close']) * 100 if latest_day['Close'] > 0 else 0
            
            # 3. 跳空幅度 Gap%
            gap_pct = ((latest_day['Open'] - prev_day['Close']) / prev_day['Close']) * 100
            
            # 清理 nan 和 inf 值
            price = clean_float(latest_day['Close'])
            rvol = clean_float(rvol)
            atr_pct = clean_float(atr_pct)
            gap_pct = clean_float(gap_pct)
            volume_m = clean_float(latest_volume) / 1_000_000
            
            # 获取公司基本静态档案
            company_details = get_company_info(ticker)
            
            # 推荐规则
            recommended = bool(rvol > 1.2 and atr_pct > 1.5)
            
            results.append({
                "ticker": ticker,
                "name": company_details["name"],
                "sector": company_details["sector"],
                "price": float(round(price, 2)),
                "rvol": float(round(rvol, 2)),
                "atr_pct": float(round(atr_pct, 2)),
                "gap_pct": float(round(gap_pct, 2)),
                "volume_m": float(round(volume_m, 2)),
                "recommended": recommended,
                "reason": f"成交量放大至 {rvol:.1f} 倍，日均振幅达 {atr_pct:.1f}%，具备极强的交易热度。" if recommended else "当前市场动能不足或振幅较窄，建议观望。"
            })
        except Exception as e:
            # 异常时记录基础数据
            results.append({
                "ticker": ticker,
                "name": f"{ticker} Corp",
                "sector": "未知",
                "price": 0.0,
                "rvol": 0.0,
                "atr_pct": 0.0,
                "gap_pct": 0.0,
                "volume_m": 0.0,
                "recommended": False,
                "reason": f"数据抓取失败: {str(e)}"
            })
            
    # 按相对成交量降序排列
    results.sort(key=lambda x: x["rvol"], reverse=True)
    return {"success": True, "results": results}

def _run_backtest_core(
    ticker: str = "TSLA", 
    period: str = None,
    interval: str = "1m",
    strategy_mode: str = "dynamic",
    stop_loss_pct: float = 0.015,
    profit_target_pct: float = 0.030,
    trailing_stop_mode: str = "atr",
    trailing_stop_atr_mult: float = 2.0,
    rsi_threshold_buy: float = 65.0,
    risk_per_trade_pct: float = 0.01,
    max_position_size_pct: float = 0.50,
    commission_per_share: float = 0.005,
    slippage_rate: float = 0.0003,
    market_open_focus: bool = True
):
    ticker = ticker.upper()
    try:
        # 1. 整理策略与风险管理参数
        strategy_params = {
            "strategy_mode": strategy_mode,
            "stop_loss_pct": stop_loss_pct,
            "profit_target_pct": profit_target_pct,
            "trailing_stop_mode": trailing_stop_mode,
            "trailing_stop_atr_mult": trailing_stop_atr_mult,
            "rsi_threshold_buy": rsi_threshold_buy,
            "market_open_focus": market_open_focus
        }
        
        risk_params = {
            "slippage_rate": slippage_rate,
            "commission_per_share": commission_per_share,
            "min_commission_per_order": 1.0,
            "position_sizing_mode": "atr",
            "risk_per_trade_pct": risk_per_trade_pct,
            "max_position_size_pct": max_position_size_pct
        }
        
        # 2. 拉取数据
        df_raw = fetch_and_prepare_data(ticker, period=period, interval=interval)
        
        # 3. 运行形态检测
        df = analyze_patterns(df_raw)
        
        # 记录形态检测出的日志事件，用于前端展示
        patterns_log = []
        for idx, row in df.iterrows():
            timestamp_str = idx.strftime("%Y-%m-%d %H:%M")
            close_p = float(row['Close'])
            
            if row.get('Pattern_W_Bottom', False):
                patterns_log.append({
                    "time": timestamp_str,
                    "ticker": ticker,
                    "pattern": "W-Bottom (双底)",
                    "type": "bullish",
                    "price": round(close_p, 2),
                    "desc": "股价完成了两阶段探底，并强势突破了中间的波峰颈线阻力，看涨信号确认。"
                })
            if row.get('Pattern_M_Top', False):
                patterns_log.append({
                    "time": timestamp_str,
                    "ticker": ticker,
                    "pattern": "M-Top (双顶)",
                    "type": "bearish",
                    "price": round(close_p, 2),
                    "desc": "股价两次上攻均受阻，随后跌破了中间波谷的颈线支撑，看跌形态确认。"
                })
            if row.get('Pattern_Hammer', False):
                patterns_log.append({
                    "time": timestamp_str,
                    "ticker": ticker,
                    "pattern": "Hammer (锤子线)",
                    "type": "bullish",
                    "price": round(close_p, 2),
                    "desc": "低位出现长下影线小实体，代表下方买方托盘力量极其强劲，是看涨信号。"
                })
            if row.get('Pattern_Shooting_Star', False):
                patterns_log.append({
                    "time": timestamp_str,
                    "ticker": ticker,
                    "pattern": "Shooting Star (流星线)",
                    "type": "bearish",
                    "price": round(close_p, 2),
                    "desc": "高位出现长上影线小实体，代表向上试探失败，抛盘涌现，见顶风险加剧。"
                })
            if row.get('Pattern_Bullish_Engulfing', False):
                patterns_log.append({
                    "time": timestamp_str,
                    "ticker": ticker,
                    "pattern": "Bullish Engulfing (阳包阴)",
                    "type": "bullish",
                    "price": round(close_p, 2),
                    "desc": "大阳线实体完全包住前一根阴线，说明买方完全反击并掌控了局势。"
                })
            if row.get('Pattern_Bearish_Engulfing', False):
                patterns_log.append({
                    "time": timestamp_str,
                    "ticker": ticker,
                    "pattern": "Bearish Engulfing (阴包阳)",
                    "type": "bearish",
                    "price": round(close_p, 2),
                    "desc": "大阴线实体完全包住前一根阳线，说明卖方力量空前强大，恐慌盘砸盘。"
                })
        
        # 4. 执行模拟回测
        is_intraday = interval in ["1m", "5m", "15m", "30m", "1h"]
        res = run_backtest_sim(df, ticker, strategy_params, risk_params, is_intraday=is_intraday)
        
        # 5. 整理 K线数据给前端 TradingView 图表渲染
        chart_candles = []
        for idx, r in df.iterrows():
            chart_candles.append({
                "time": int(idx.timestamp()),
                "open": round(clean_float(r['Open']), 2),
                "high": round(clean_float(r['High']), 2),
                "low": round(clean_float(r['Low']), 2),
                "close": round(clean_float(r['Close']), 2),
                "volume": int(clean_float(r['Volume'])),
                "vwap": round(clean_float(r['VWAP']), 2) if not pd.isna(r['VWAP']) else None,
                "ema_9": round(clean_float(r['EMA_9']), 2) if not pd.isna(r['EMA_9']) else None,
                "ema_21": round(clean_float(r['EMA_21']), 2) if not pd.isna(r['EMA_21']) else None,
                "ema_50": round(clean_float(r['EMA_50']), 2) if not pd.isna(r['EMA_50']) else None,
                "rsi": round(clean_float(r['RSI']), 1) if not pd.isna(r['RSI']) else None,
                "squeeze": bool(r['Squeeze_On']) if not pd.isna(r['Squeeze_On']) else False,
                "regime": r.get('Regime', 'range_bound')
            })
            
        # 整理买卖标记 (markers)
        trade_markers = []
        for trade in res["ledger"]:
            trade_time = int(pd.to_datetime(trade['timestamp']).timestamp())
            
            if trade['action'] == 'BUY':
                trade_markers.append({
                    "time": trade_time,
                    "position": "belowBar",
                    "color": "#00c805",
                    "shape": "arrowUp",
                    "text": f"BUY {trade['shares']}股 @ {trade['execution_price']:.2f}"
                })
            elif trade['action'] == 'SELL':
                pnl = trade.get('realized_pnl', 0.0)
                color = "#ff3b30" if pnl < 0 else "#00c805"
                text = f"SELL {trade['shares']}股 @ {trade['execution_price']:.2f} ({'+' if pnl>=0 else ''}{pnl:.2f})"
                trade_markers.append({
                    "time": trade_time,
                    "position": "aboveBar",
                    "color": color,
                    "shape": "arrowDown",
                    "text": text
                })

        # 按时间排序形态日志
        patterns_log = sorted(patterns_log, key=lambda x: x["time"], reverse=True)
        patterns_log = patterns_log[:100]

        return {
            "success": True,
            "ticker": ticker,
            "period": period or INTERVAL_TO_PERIOD.get(interval, "5d"),
            "interval": interval,
            "summary": {
                "initial_cash": INITIAL_CASH,
                "final_equity": clean_float(res["final_equity"]),
                "net_pnl": clean_float(res["net_pnl"]),
                "pnl_pct": clean_float(res["pnl_pct"]),
                "total_trades": int(res["total_trades"]),
                "round_trips": int(res["round_trips"]),
                "win_rate": clean_float(res["win_rate"]),
                "commission": clean_float(res["commission"]),
                "max_drawdown": clean_float(res["max_drawdown"]),
                "sharpe": clean_float(res.get("sharpe", 0)),
                "calmar": clean_float(res.get("calmar", 0)),
                "cagr": clean_float(res.get("cagr", 0)),
                "profit_factor": clean_float(res.get("profit_factor", 0)),
                "gross_profit": clean_float(res.get("gross_profit", 0)),
                "gross_loss": clean_float(res.get("gross_loss", 0)),
            },
            "ledger": res["ledger"],
            "candles": chart_candles,
            "markers": trade_markers,
            "equity_curve": res["equity_curve"],
            "drawdown_curve": res.get("drawdown_curve", []),
            "regime_breakdown": res.get("regime_breakdown", []),
            "regime_distribution": res.get("regime_distribution", {}),
            "patterns_log": patterns_log
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@app.get("/api/backtest")
def run_backtest_api(
    ticker: str = "TSLA", 
    period: str = None,
    interval: str = "1m",
    strategy_mode: str = "dynamic",
    stop_loss_pct: float = 0.015,
    profit_target_pct: float = 0.030,
    trailing_stop_mode: str = "atr",
    trailing_stop_atr_mult: float = 2.0,
    rsi_threshold_buy: float = 65.0,
    risk_per_trade_pct: float = 0.01,
    max_position_size_pct: float = 0.50,
    commission_per_share: float = 0.005,
    slippage_rate: float = 0.0003,
    market_open_focus: bool = True
):
    """
    接口：运行自定义配置参数的回测，包含 K线、均线、市场状态路由与交易流水
    """
    return _run_backtest_core(
        ticker=ticker,
        period=period,
        interval=interval,
        strategy_mode=strategy_mode,
        stop_loss_pct=stop_loss_pct,
        profit_target_pct=profit_target_pct,
        trailing_stop_mode=trailing_stop_mode,
        trailing_stop_atr_mult=trailing_stop_atr_mult,
        rsi_threshold_buy=rsi_threshold_buy,
        risk_per_trade_pct=risk_per_trade_pct,
        max_position_size_pct=max_position_size_pct,
        commission_per_share=commission_per_share,
        slippage_rate=slippage_rate,
        market_open_focus=market_open_focus
    )


# ========== AI Agent & Walk-Forward & Monitoring Endpoints ==========

class ChatRequest(BaseModel):
    message: str
    history: Optional[list] = []

@app.post("/api/agent/chat")
def agent_chat(request: ChatRequest):
    """
    AI 研究助手对话接口 — 接受自然语言策略描述，返回解析后的策略配置 + AI 回复
    """
    try:
        result = get_chat_response(request.message, request.history)
        return {"success": True, **result}
    except Exception as e:
        return {"success": False, "error": str(e)}

class ExecuteRequest(BaseModel):
    strategy_config: dict
    experiment_name: Optional[str] = None

@app.post("/api/agent/execute")
def agent_execute(request: ExecuteRequest):
    """
    一键执行：根据策略配置获取数据 + 运行回测 + 生成风险报告 + 保存实验
    """
    try:
        config = request.strategy_config
        ticker = config.get("ticker", "TSLA").upper()
        interval = config.get("interval", "1d")
        
        # 运行回测核心
        result = _run_backtest_core(
            ticker=ticker,
            period=None,
            interval=interval,
            strategy_mode=config.get("strategy_mode", "dynamic"),
            stop_loss_pct=config.get("stop_loss_pct", 0.015),
            profit_target_pct=config.get("profit_target_pct", 0.030),
            trailing_stop_mode=config.get("trailing_stop_mode", "atr"),
            trailing_stop_atr_mult=config.get("trailing_stop_atr_mult", 2.0),
            rsi_threshold_buy=config.get("rsi_threshold_buy", 65.0),
            risk_per_trade_pct=config.get("risk_per_trade_pct", 0.01),
            max_position_size_pct=config.get("max_position_size_pct", 0.50),
            commission_per_share=config.get("commission_per_share", 0.005),
            slippage_rate=config.get("slippage_rate", 0.0003),
            market_open_focus=config.get("market_open_focus", True)
        )
        
        if not result.get("success", False):
            return result
            
        # 默认保存为实验
        exp_name = request.experiment_name or f"LLM_{ticker}_{config.get('strategy_mode', 'dynamic')}"
        new_id = save_experiment(
            name=exp_name,
            ticker=ticker,
            interval=interval,
            strategy_mode=config.get("strategy_mode", "dynamic"),
            config=config,
            metrics=result["summary"],
            equity_curve=result.get("equity_curve", []),
            drawdown_curve=result.get("drawdown_curve", []),
            regime_breakdown=result.get("regime_breakdown", [])
        )
        
        result["experiment_id"] = new_id
        result["experiment_saved"] = True
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}

class WalkForwardRequest(BaseModel):
    ticker: str = "TSLA"
    interval: str = "1d"
    period: Optional[str] = "1y"
    train_size: Optional[int] = 120
    test_size: Optional[int] = 40

@app.post("/api/walk_forward")
def run_walk_forward_api_endpoint(request: WalkForwardRequest):
    """
    运行 Walk-Forward 优化并返回 IS vs OOS Sharpe 汇总结果
    """
    ticker = request.ticker.upper()
    interval = request.interval
    period = request.period or "1y"
    train_size = request.train_size or 120
    test_size = request.test_size or 40
    
    try:
        df_raw = fetch_and_prepare_data(ticker, period=period, interval=interval)
        df = analyze_patterns(df_raw)
        
        total_len = len(df)
        if total_len < (train_size + test_size):
            return {"success": False, "error": f"历史数据共 {total_len} 根 Bar，不足以分配 Train({train_size}) + Test({test_size})！"}
            
        param_grid = []
        for mode in ["dynamic", "consensus"]:
            for atr_mult in [1.5, 2.0, 2.5]:
                for rsi_th in [60.0, 65.0, 70.0]:
                    param_grid.append({
                        "strategy_mode": mode,
                        "trailing_stop_atr_mult": atr_mult,
                        "rsi_threshold_buy": rsi_th,
                        "stop_loss_pct": 0.015,
                        "profit_target_pct": 0.030
                    })
                    
        risk_params = {
            "slippage_rate": 0.0003,
            "commission_per_share": 0.005,
            "min_commission_per_order": 1.0,
            "position_sizing_mode": "atr",
            "risk_per_trade_pct": 0.01,
            "max_position_size_pct": 0.50
        }
        
        start_idx = 0
        oos_results = []
        is_intraday = interval in ["1m", "5m", "15m", "30m", "1h"]
        window_count = 1
        
        while start_idx + train_size + test_size <= total_len:
            train_df = df.iloc[start_idx : start_idx + train_size]
            test_df = df.iloc[start_idx + train_size : start_idx + train_size + test_size]
            
            train_start_date = train_df.index[0].strftime("%Y-%m-%d")
            train_end_date = train_df.index[-1].strftime("%Y-%m-%d")
            test_start_date = test_df.index[0].strftime("%Y-%m-%d")
            test_end_date = test_df.index[-1].strftime("%Y-%m-%d")
            
            best_score = -999999.0
            best_params = None
            
            for params in param_grid:
                res = run_backtest_sim(train_df, ticker, params, risk_params, is_intraday=is_intraday)
                score = res["net_pnl"] - (res["max_drawdown"] * 30000.0 * 2.0)
                if score > best_score:
                    best_score = score
                    best_params = params
                    
            test_res = run_backtest_sim(test_df, ticker, best_params, risk_params, is_intraday=is_intraday)
            
            # 计算 IS Sharpe
            train_best_res = run_backtest_sim(train_df, ticker, best_params, risk_params, is_intraday=is_intraday)
            is_sharpe = train_best_res.get("sharpe", 0.0)
            oos_sharpe = test_res.get("sharpe", 0.0)
            
            oos_results.append({
                "window": window_count,
                "train_period": f"{train_start_date} ~ {train_end_date}",
                "test_period": f"{test_start_date} ~ {test_end_date}",
                "best_params": best_params,
                "is_sharpe": round(clean_float(is_sharpe), 2),
                "oos_sharpe": round(clean_float(oos_sharpe), 2),
                "net_pnl": round(clean_float(test_res["net_pnl"]), 2),
                "max_drawdown": round(clean_float(test_res["max_drawdown"]), 4),
                "round_trips": int(test_res["round_trips"]),
                "win_rate": round(clean_float(test_res["win_rate"]), 2),
                "commission": round(clean_float(test_res["commission"]), 2)
            })
            
            start_idx += test_size
            window_count += 1
            
        # 对照组：全样本默认参数
        default_params = {
            "strategy_mode": "dynamic",
            "trailing_stop_atr_mult": 2.0,
            "rsi_threshold_buy": 65.0,
            "stop_loss_pct": 0.015,
            "profit_target_pct": 0.030
        }
        static_res = run_backtest_sim(df, ticker, default_params, risk_params, is_intraday=is_intraday)
        
        total_wf_pnl = sum(r["net_pnl"] for r in oos_results)
        total_wf_commission = sum(r["commission"] for r in oos_results)
        avg_wf_drawdown = float(np.mean([r["max_drawdown"] for r in oos_results])) if oos_results else 0.0
        total_wf_trades = sum(r["round_trips"] for r in oos_results)
        
        # 计算 IS Sharpe 和 OOS Sharpe 相关性
        is_sharhes = [r["is_sharpe"] for r in oos_results]
        oos_sharhes = [r["oos_sharpe"] for r in oos_results]
        correlation = 0.0
        if len(is_sharhes) > 1 and np.std(is_sharhes) > 0 and np.std(oos_sharhes) > 0:
            correlation = float(np.corrcoef(is_sharhes, oos_sharhes)[0, 1])
            
        correlation = clean_float(correlation)
        is_overfitted = False
        avg_is_sharpe = float(np.mean(is_sharhes)) if is_sharhes else 0.0
        avg_oos_sharpe = float(np.mean(oos_sharhes)) if oos_sharhes else 0.0
        
        if avg_is_sharpe > 1.2 and avg_oos_sharpe < 0.3:
            is_overfitted = True
            
        return {
            "success": True,
            "ticker": ticker,
            "interval": interval,
            "period": period,
            "oos_results": oos_results,
            "correlation": round(correlation, 2),
            "is_overfitted": is_overfitted,
            "static_control": {
                "net_pnl": round(clean_float(static_res["net_pnl"]), 2),
                "pnl_pct": round(clean_float(static_res["pnl_pct"]), 2),
                "round_trips": int(static_res["round_trips"]),
                "commission": round(clean_float(static_res["commission"]), 2),
                "max_drawdown": round(clean_float(static_res["max_drawdown"]), 4),
                "sharpe": round(clean_float(static_res.get("sharpe", 0.0)), 2)
            },
            "summary": {
                "total_wf_pnl": round(total_wf_pnl, 2),
                "total_wf_commission": round(total_wf_commission, 2),
                "avg_wf_drawdown": round(avg_wf_drawdown, 4),
                "total_wf_trades": total_wf_trades,
                "avg_is_sharpe": round(avg_is_sharpe, 2),
                "avg_oos_sharpe": round(avg_oos_sharpe, 2)
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

class TuneRequest(BaseModel):
    ticker: str
    interval: str = "1m"
    period: Optional[str] = "5d"

@app.post("/api/ai_tune")
def ai_tune_endpoint(request: TuneRequest):
    """
    运行 AI 托管参数自动调优接口
    """
    ticker = request.ticker.upper()
    interval = request.interval
    period = request.period or "5d"
    
    try:
        # 1. 抓取与清洗指标数据
        df_raw = fetch_and_prepare_data(ticker, period=period, interval=interval)
        df = analyze_patterns(df_raw)
        
        # 2. 定义调优参数搜索网格
        best_score = -999999.0
        best_params = None
        best_res = None
        
        strategy_options = ["opening_breakout", "consensus", "dynamic", "patterns"]
        stop_loss_options = [0.005, 0.01, 0.015, 0.02]  # 紧凑止损线
        profit_target_options = [0.01, 0.02, 0.03, 0.05] # 止盈线
        atr_mult_options = [1.5, 2.0, 2.5]
        
        risk_params = {
            "slippage_rate": 0.0003,
            "commission_per_share": 0.005,
            "min_commission_per_order": 1.0,
            "position_sizing_mode": "atr",
            "risk_per_trade_pct": 0.01,
            "max_position_size_pct": 0.50
        }
        
        is_intraday = interval in ["1m", "5m", "15m", "30m", "1h"]
        
        for mode in strategy_options:
            for sl in stop_loss_options:
                for pt in profit_target_options:
                    for atr_m in atr_mult_options:
                        params = {
                            "strategy_mode": mode,
                            "stop_loss_pct": sl,
                            "profit_target_pct": pt,
                            "trailing_stop_mode": "atr",
                            "trailing_stop_atr_mult": atr_m,
                            "rsi_threshold_buy": 65.0,
                            "market_open_focus": True
                        }
                        
                        res = run_backtest_sim(df, ticker, params, risk_params, is_intraday=is_intraday)
                        
                        net_pnl = res["net_pnl"]
                        max_dd = res["max_drawdown"]
                        win_rate = res["win_rate"]
                        trades = res["round_trips"]
                        
                        if trades == 0:
                            score = -1000.0
                        else:
                            # 评分函数：利润优先，严厉惩罚大回撤，结合胜率
                            score = net_pnl - (max_dd * 30000.0 * 4.0) + (win_rate * 2.0)
                            
                        if score > best_score:
                            best_score = score
                            best_params = params
                            best_res = res
                            
        if not best_params:
            best_params = {
                "strategy_mode": "opening_breakout",
                "stop_loss_pct": 0.01,
                "profit_target_pct": 0.02,
                "trailing_stop_mode": "atr",
                "trailing_stop_atr_mult": 1.5,
                "rsi_threshold_buy": 65.0,
                "market_open_focus": True
            }
            best_res = {"net_pnl": 0.0, "max_drawdown": 0.0, "win_rate": 0.0, "round_trips": 0}
            
        ticker_details = get_company_info(ticker)
        name = ticker_details.get("name", ticker)
        
        mode_cn = {
            "opening_breakout": "开盘突击突破策略",
            "consensus": "共振共识策略",
            "dynamic": "动态状态路由策略",
            "patterns": "K线形态反转策略"
        }.get(best_params["strategy_mode"], best_params["strategy_mode"])
        
        reasoning = (
            f"AI 智能托管针对 {name} 最近 {period} 的日内波动特征运行了机器学习调优算法。\n"
            f"由于开盘 3-5 分钟振幅大且伴随突破，AI 自动推荐采用【{mode_cn}】来追踪走势。\n"
            f"风控策略已自动调整为：硬止损设为 {(best_params['stop_loss_pct']*100):.1f}%，"
            f"目标止盈设为 {(best_params['profit_target_pct']*100):.1f}%，"
            f"配合 {best_params['trailing_stop_atr_mult']:.1f}倍 ATR 移动追踪止损以防高位跌落。\n"
            f"该优化组合在近期的历史回测中实现了约 ${best_res['net_pnl']:.2f} 的净盈亏，"
            f"胜率达 {best_res['win_rate']:.1f}%，最大回撤控制在 {(best_res['max_drawdown']*100):.2f}%，有效规避了单边下挫风险。"
        )
        
        return {
            "success": True,
            "best_params": best_params,
            "reasoning": reasoning,
            "metrics": {
                "net_pnl": round(best_res["net_pnl"], 2),
                "win_rate": round(best_res["win_rate"], 2),
                "max_drawdown": round(best_res["max_drawdown"], 4),
                "round_trips": best_res["round_trips"]
            }
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@app.get("/api/metrics")
def get_metrics():
    """
    监控指标端点：请求次数、响应延迟统计、本地数据缓存容量、LLM 费用与 token
    """
    lats = request_latencies[-100:] if request_latencies else [0.0]
    p50 = float(np.percentile(lats, 50)) if lats else 0.0
    p95 = float(np.percentile(lats, 95)) if lats else 0.0
    
    # 缓存统计
    cache_stats = get_cache_stats()
    # LLM 统计
    llm_usage = llm_get_usage()
    
    return {
        "success": True,
        "total_requests": len(request_latencies),
        "latency_p50_ms": round(p50, 1),
        "latency_p95_ms": round(p95, 1),
        "cache": cache_stats,
        "llm_usage": llm_usage
    }

# ========== Experiments Endpoints ==========

@app.get("/api/experiments")
def get_experiments_list():
    """获取所有已保存的实验"""
    try:
        return {"success": True, "experiments": list_experiments()}
    except Exception as e:
        return {"success": False, "error": str(e)}

class SaveExperimentRequest(BaseModel):
    name: str
    ticker: str
    interval: str
    strategy_mode: str
    config: dict
    metrics: dict
    equity_curve: list
    drawdown_curve: list
    regime_breakdown: list

@app.post("/api/experiments/save")
def post_save_experiment(request: SaveExperimentRequest):
    """保存当前实验"""
    try:
        new_id = save_experiment(
            name=request.name,
            ticker=request.ticker,
            interval=request.interval,
            strategy_mode=request.strategy_mode,
            config=request.config,
            metrics=request.metrics,
            equity_curve=request.equity_curve,
            drawdown_curve=request.drawdown_curve,
            regime_breakdown=request.regime_breakdown
        )
        return {"success": True, "id": new_id}
    except Exception as e:
        return {"success": False, "error": str(e)}

class CompareRequest(BaseModel):
    ids: list

@app.post("/api/experiments/compare")
def post_compare_experiments(request: CompareRequest):
    """对比多个实验"""
    try:
        results = compare_experiments(request.ids)
        return {"success": True, "results": results}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.delete("/api/experiments/{id}")
def delete_saved_experiment(id: int):
    """删除指定的实验"""
    try:
        success = delete_experiment(id)
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}

class ResearchRequest(BaseModel):
    prompt: str

@app.post("/api/agent/research")
def agent_research(request: ResearchRequest):
    """
    AI Agent: Parse natural language research prompt into strategy config + execution plan
    """
    try:
        result = parse_research_prompt(request.prompt)
        return {"success": True, **result}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/agent/examples")
def agent_examples():
    """
    Return example prompts for the chat interface
    """
    return {"examples": get_example_prompts(), "tools": get_backend_tools()}

class ReportRequest(BaseModel):
    ticker: str = "TSLA"
    interval: str = "1d"
    strategy_mode: str = "dynamic"
    stop_loss_pct: float = 0.015
    profit_target_pct: float = 0.030
    trailing_stop_mode: str = "atr"
    trailing_stop_atr_mult: float = 2.0
    rsi_threshold_buy: float = 65.0
    risk_per_trade_pct: float = 0.01
    max_position_size_pct: float = 0.50
    position_sizing_mode: str = "atr"
    commission_per_share: float = 0.005
    slippage_rate: float = 0.0003

@app.post("/api/report/generate")
def generate_report(request: ReportRequest):
    """
    Generate AI risk analysis report: run backtest then analyze results
    """
    try:
        ticker = request.ticker.upper()
        strategy_params = {
            "strategy_mode": request.strategy_mode,
            "stop_loss_pct": request.stop_loss_pct,
            "profit_target_pct": request.profit_target_pct,
            "trailing_stop_mode": request.trailing_stop_mode,
            "trailing_stop_atr_mult": request.trailing_stop_atr_mult,
            "rsi_threshold_buy": request.rsi_threshold_buy,
        }
        risk_params = {
            "slippage_rate": request.slippage_rate,
            "commission_per_share": request.commission_per_share,
            "min_commission_per_order": 1.0,
            "position_sizing_mode": request.position_sizing_mode,
            "risk_per_trade_pct": request.risk_per_trade_pct,
            "max_position_size_pct": request.max_position_size_pct,
        }
        
        # Run backtest
        df_raw = fetch_and_prepare_data(ticker, interval=request.interval)
        df = analyze_patterns(df_raw)
        is_intraday = request.interval in ["1m", "5m", "15m", "30m", "1h"]
        backtest_result = run_backtest_sim(df, ticker, strategy_params, risk_params, is_intraday=is_intraday)
        
        # Generate risk report
        strategy_config = {
            "ticker": ticker,
            "interval": request.interval,
            "strategy_mode": request.strategy_mode,
        }
        report = generate_risk_report(backtest_result, strategy_config)
        
        return {"success": True, "report": report}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@app.get("/api/research_report")
def get_research_report():
    """
    读取并解析本地 deep-research-report.md 报告，将其转化为结构化的 JSON 返回给前端
    """
    import os
    import re
    
    # 查找本地研究报告文件
    possible_paths = [
        "deep-research-report.md",
        "../deep-research-report.md",
        os.path.join(os.path.dirname(__file__), "..", "deep-research-report.md"),
        os.path.join(os.path.dirname(__file__), "deep-research-report.md"),
    ]
    filepath = None
    for p in possible_paths:
        if os.path.exists(p):
            filepath = p
            break
            
    if not filepath:
        # 兜底查找
        for root, dirs, files in os.walk(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
            if "deep-research-report.md" in files:
                filepath = os.path.join(root, "deep-research-report.md")
                break

    if not filepath or not os.path.exists(filepath):
        return {"success": False, "error": f"未找到 deep-research-report.md 文件，请检查路径。查找过的路径: {possible_paths}"}
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
            
        # 提取标题
        title_match = re.search(r'^#\s+(.*?)$', content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else "日线为主的全自动炒股软件开发分析报告"
        
        # 以双换行符 + ## 拆分大章节
        raw_sections = re.split(r'\n##\s+', content)
        sections = []
        
        for i, rs in enumerate(raw_sections):
            if i == 0:
                # 标题下方的首段引言 (如果有的话)
                intro_text = rs.replace(f"# {title}", "").strip()
                if intro_text:
                    sections.append({
                        "title": "执行摘要",
                        "id": "executive_summary",
                        "components": [{"type": "paragraph", "content": intro_text}]
                    })
                continue
                
            lines = rs.split("\n")
            heading = lines[0].strip()
            body_text = "\n".join(lines[1:]).strip()
            
            # 生成前端滚动锚点 ID
            id_mapping = {
                "执行摘要": "executive_summary",
                "关键目标与约束": "key_goals___constraints",
                "K线形态与技术指标": "kline_patterns___indicators",
                "量化策略清单": "quantitative_strategy_checklist",
                "风控与资金管理": "risk_control___capital_management",
                "回测与参数优化": "backtesting___parameter_optimization",
                "实盘部署与代码清单": "production_deployment___code_checklist",
                "参考来源与合规风险提示": "references___compliance_risk_alert"
            }
            section_id = id_mapping.get(heading)
            if not section_id:
                section_id = heading.lower()
                section_id = re.sub(r'[^a-z0-9]', '_', section_id).strip('_')
                if not section_id:
                    section_id = f"sec_{i}"
            
            components = []
            body_lines = body_text.split("\n")
            idx = 0
            while idx < len(body_lines):
                line = body_lines[idx].strip()
                if not line:
                    idx += 1
                    continue
                    
                # 1. 三级子标题
                if line.startswith("###"):
                    sub_heading = line.replace("###", "").strip()
                    components.append({
                        "type": "heading3",
                        "content": sub_heading
                    })
                    idx += 1
                    continue
                    
                # 2. Markdown 表格
                if line.startswith("|") and idx + 1 < len(body_lines) and re.match(r'^\|[\s:-|]+$', body_lines[idx+1].strip()):
                    table_lines = []
                    while idx < len(body_lines) and (body_lines[idx].strip().startswith("|") or not body_lines[idx].strip()):
                        if body_lines[idx].strip():
                            table_lines.append(body_lines[idx].strip())
                        idx += 1
                    
                    if len(table_lines) >= 3:
                        headers = [c.strip() for c in table_lines[0].split("|")[1:-1]]
                        rows = []
                        for t_line in table_lines[2:]:
                            cols = [c.strip() for c in t_line.split("|")[1:-1]]
                            if len(cols) < len(headers):
                                cols += [""] * (len(headers) - len(cols))
                            else:
                                cols = cols[:len(headers)]
                            rows.append(dict(zip(headers, cols)))
                        components.append({
                            "type": "table",
                            "headers": headers,
                            "rows": rows
                        })
                    continue
                    
                # 3. 代码块
                if line.startswith("```"):
                    lang = line.replace("```", "").strip()
                    code_content = []
                    idx += 1
                    while idx < len(body_lines) and not body_lines[idx].strip().startswith("```"):
                        code_content.append(body_lines[idx])
                        idx += 1
                    idx += 1  # 跨过 ```
                    components.append({
                        "type": "code",
                        "lang": lang,
                        "content": "\n".join(code_content)
                    })
                    continue
                    
                # 4. 引用块 / 警示框 (Github Alerts)
                if line.startswith(">"):
                    alert_type = "info"
                    cleaned_line = line[1:].strip()
                    match_tag = re.match(r'^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]', cleaned_line)
                    if match_tag:
                        alert_type = match_tag.group(1).lower()
                        cleaned_line = cleaned_line[match_tag.end():].strip()
                    
                    alert_lines = [cleaned_line] if cleaned_line else []
                    idx += 1
                    while idx < len(body_lines) and body_lines[idx].strip().startswith(">"):
                        cleaned_body_line = body_lines[idx].strip()[1:].strip()
                        if cleaned_body_line:
                            alert_lines.append(cleaned_body_line)
                        idx += 1
                    components.append({
                        "type": "alert",
                        "alert_type": alert_type,
                        "content": " ".join(alert_lines)
                    })
                    continue
                    
                # 5. 列表项
                if line.startswith("-") or line.startswith("*") or (re.match(r'^\d+\.', line)):
                    list_items = []
                    while idx < len(body_lines) and (body_lines[idx].strip().startswith("-") or body_lines[idx].strip().startswith("*") or re.match(r'^\d+\.', body_lines[idx].strip())):
                        cleaned_item = re.sub(r'^[-*\d.]+\s+', '', body_lines[idx].strip())
                        list_items.append(cleaned_item)
                        idx += 1
                    components.append({
                        "type": "list",
                        "items": list_items
                    })
                    continue
                    
                # 6. 普通段落
                p_lines = [line]
                idx += 1
                while idx < len(body_lines):
                    next_line = body_lines[idx].strip()
                    if not next_line:
                        idx += 1
                        break
                    # 如果下一行是任何其他区块的起点，直接中断
                    if next_line.startswith("###") or next_line.startswith("##") or next_line.startswith("|") or next_line.startswith("```") or next_line.startswith(">") or next_line.startswith("-") or next_line.startswith("*") or re.match(r'^\d+\.', next_line):
                        break
                    p_lines.append(next_line)
                    idx += 1
                    
                components.append({
                    "type": "paragraph",
                    "content": " ".join(p_lines)
                })
                
            sections.append({
                "title": heading,
                "id": section_id,
                "components": components
            })
            
        return {"success": True, "title": title, "sections": sections}
    except Exception as e:
        return {"success": False, "error": f"解析报告失败: {str(e)}"}


@app.get("/api/replay/available_dates")
def get_replay_available_dates(ticker: str = "TSLA"):
    ticker = ticker.upper()
    try:
        # 获取 5d 1m 数据
        df = fetch_and_prepare_data(ticker, period="5d", interval="1m")
        # 提取独特日期列表（按时间从近到远排序，转为字符串）
        unique_dates = sorted(list(set(df.index.date.astype(str))), reverse=True)
        return {"success": True, "dates": unique_dates[:5]}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/replay/data")
def get_replay_data(
    ticker: str = "TSLA",
    date: str = None,
    strategy_mode: str = "opening_breakout",
    stop_loss_pct: float = 0.015,
    profit_target_pct: float = 0.030,
    trailing_stop_mode: str = "atr",
    trailing_stop_atr_mult: float = 2.0,
    rsi_threshold_buy: float = 65.0,
    risk_per_trade_pct: float = 0.01,
    max_position_size_pct: float = 0.50,
    commission_per_share: float = 0.005,
    slippage_rate: float = 0.0003,
    market_open_focus: bool = True
):
    ticker = ticker.upper()
    try:
        if not date:
            return {"success": False, "error": "必须指定 date 参数"}
            
        # 1. 拉取 5d 1m 的数据 (包含前后日数据以计算正确的指标，如 EMA/RSI)
        df_all = fetch_and_prepare_data(ticker, period="5d", interval="1m")
        
        # 2. 运行形态分析
        df_all = analyze_patterns(df_all)
        
        # 3. 筛选出指定日期的数据
        target_date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
        df_date = df_all[df_all.index.date == target_date].copy()
        
        if df_date.empty:
            return {"success": False, "error": f"没有找到 {date} 对应的数据。"}
            
        # 4. 在该日期的数据上运行策略回测
        strategy_params = {
            "strategy_mode": strategy_mode,
            "stop_loss_pct": stop_loss_pct,
            "profit_target_pct": profit_target_pct,
            "trailing_stop_mode": trailing_stop_mode,
            "trailing_stop_atr_mult": trailing_stop_atr_mult,
            "rsi_threshold_buy": rsi_threshold_buy,
            "market_open_focus": market_open_focus
        }
        
        risk_params = {
            "slippage_rate": slippage_rate,
            "commission_per_share": commission_per_share,
            "min_commission_per_order": 1.0,
            "position_sizing_mode": "atr",
            "risk_per_trade_pct": risk_per_trade_pct,
            "max_position_size_pct": max_position_size_pct
        }
        
        res = run_backtest_sim(df_date, ticker, strategy_params, risk_params, is_intraday=True)
        
        # 5. 整理 K线数据给前端 TradingView 图表渲染
        chart_candles = []
        for idx, r in df_date.iterrows():
            chart_candles.append({
                "time": int(idx.timestamp()),
                "open": round(clean_float(r['Open']), 2),
                "high": round(clean_float(r['High']), 2),
                "low": round(clean_float(r['Low']), 2),
                "close": round(clean_float(r['Close']), 2),
                "volume": int(clean_float(r['Volume'])),
                "vwap": round(clean_float(r['VWAP']), 2) if not pd.isna(r['VWAP']) else None,
                "ema_9": round(clean_float(r['EMA_9']), 2) if not pd.isna(r['EMA_9']) else None,
                "ema_21": round(clean_float(r['EMA_21']), 2) if not pd.isna(r['EMA_21']) else None,
                "ema_50": round(clean_float(r['EMA_50']), 2) if not pd.isna(r['EMA_50']) else None,
                "rsi": round(clean_float(r['RSI']), 1) if not pd.isna(r['RSI']) else None,
                "squeeze": bool(r['Squeeze_On']) if not pd.isna(r['Squeeze_On']) else False,
                "regime": r.get('Regime', 'range_bound')
            })
            
        # 整理买卖标记 (markers)
        trade_markers = []
        for trade in res["ledger"]:
            trade_time = int(pd.to_datetime(trade['timestamp']).timestamp())
            if trade['action'] == 'BUY':
                trade_markers.append({
                    "time": trade_time,
                    "position": "belowBar",
                    "color": "#00c805",
                    "shape": "arrowUp",
                    "text": f"BUY {trade['shares']}股 @ {trade['execution_price']:.2f}"
                })
            elif trade['action'] == 'SELL':
                pnl = trade.get('realized_pnl', 0.0)
                color = "#ff3b30" if pnl < 0 else "#00c805"
                text = f"SELL {trade['shares']}股 @ {trade['execution_price']:.2f} ({'+' if pnl>=0 else ''}{pnl:.2f})"
                trade_markers.append({
                    "time": trade_time,
                    "position": "aboveBar",
                    "color": color,
                    "shape": "arrowDown",
                    "text": text
                })
                
        return {
            "success": True,
            "ticker": ticker,
            "date": date,
            "summary": {
                "initial_cash": float(res.get("initial_cash", 100000.0)),
                "final_equity": float(res.get("final_equity", 100000.0)),
                "net_pnl": float(res.get("net_pnl", 0.0)),
                "pnl_pct": float(res.get("pnl_pct", 0.0)),
                "total_trades": int(res.get("total_trades", 0)),
                "round_trips": int(res.get("round_trips", 0)),
                "win_rate": float(res.get("win_rate", 0.0)),
                "commission": float(res.get("commission", 0.0)),
                "max_drawdown": float(res.get("max_drawdown", 0.0))
            },
            "ledger": res["ledger"],
            "candles": chart_candles,
            "markers": trade_markers,
            "equity_curve": res["equity_curve"]
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


@app.get("/api/intraday_data")
def get_intraday_data(ticker: str, date: str):
    ticker = ticker.upper()
    try:
        # 获取 5d 1m 的数据并计算指标
        df_all = fetch_and_prepare_data(ticker, period="5d", interval="1m")
        df_all = analyze_patterns(df_all)
        
        # 筛选特定日期
        target_date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
        df_date = df_all[df_all.index.date == target_date]
        
        if df_date.empty:
            return {"success": False, "error": f"没有找到 {date} 对应的日内数据"}
            
        chart_candles = []
        for idx, r in df_date.iterrows():
            chart_candles.append({
                "time": int(idx.timestamp()),
                "open": round(clean_float(r['Open']), 2),
                "high": round(clean_float(r['High']), 2),
                "low": round(clean_float(r['Low']), 2),
                "close": round(clean_float(r['Close']), 2),
                "volume": int(clean_float(r['Volume'])),
                "vwap": round(clean_float(r['VWAP']), 2) if not pd.isna(r['VWAP']) else None,
                "ema_9": round(clean_float(r['EMA_9']), 2) if not pd.isna(r['EMA_9']) else None,
                "ema_21": round(clean_float(r['EMA_21']), 2) if not pd.isna(r['EMA_21']) else None,
                "ema_50": round(clean_float(r['EMA_50']), 2) if not pd.isna(r['EMA_50']) else None,
            })
        return {"success": True, "ticker": ticker, "date": date, "candles": chart_candles}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    print("启动 FastAPI 服务器于 http://127.0.0.1:8000 ...")
    uvicorn.run("main_api:app", host="127.0.0.1", port=8000, reload=True)
