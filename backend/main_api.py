# backend/main_api.py

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import datetime
import pandas as pd
import numpy as np
import yfinance as yf

from app.config import INITIAL_CASH, WATCHLIST, FORCE_LIQUIDATION_TIME
from app.data_manager import fetch_and_prepare_data, get_company_info, calculate_atr, INTERVAL_TO_PERIOD
from app.patterns import analyze_patterns
from app.simulator import run_backtest_sim

app = FastAPI(title="Quont.ai API Server")

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
            
            # 获取公司基本静态档案
            company_details = get_company_info(ticker)
            
            # 推荐规则
            recommended = bool(rvol > 1.2 and atr_pct > 1.5)
            
            results.append({
                "ticker": ticker,
                "name": company_details["name"],
                "sector": company_details["sector"],
                "price": float(round(latest_day['Close'], 2)),
                "rvol": float(round(rvol, 2)),
                "atr_pct": float(round(atr_pct, 2)),
                "gap_pct": float(round(gap_pct, 2)),
                "volume_m": float(round(float(latest_volume) / 1_000_000, 2)),
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
    position_sizing_mode: str = "atr",
    commission_per_share: float = 0.005,
    slippage_rate: float = 0.0003
):
    """
    接口：运行自定义配置参数的回测，包含 K线、均线、市场状态路由与交易流水
    """
    ticker = ticker.upper()
    try:
        # 1. 整理策略与风险管理参数
        strategy_params = {
            "strategy_mode": strategy_mode,
            "stop_loss_pct": stop_loss_pct,
            "profit_target_pct": profit_target_pct,
            "trailing_stop_mode": trailing_stop_mode,
            "trailing_stop_atr_mult": trailing_stop_atr_mult,
            "rsi_threshold_buy": rsi_threshold_buy
        }
        
        risk_params = {
            "slippage_rate": slippage_rate,
            "commission_per_share": commission_per_share,
            "min_commission_per_order": 1.0,
            "position_sizing_mode": position_sizing_mode,
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
                "open": round(float(r['Open']), 2),
                "high": round(float(r['High']), 2),
                "low": round(float(r['Low']), 2),
                "close": round(float(r['Close']), 2),
                "volume": int(r['Volume']),
                "vwap": round(float(r['VWAP']), 2) if not pd.isna(r['VWAP']) else None,
                "ema_9": round(float(r['EMA_9']), 2) if not pd.isna(r['EMA_9']) else None,
                "ema_21": round(float(r['EMA_21']), 2) if not pd.isna(r['EMA_21']) else None,
                "ema_50": round(float(r['EMA_50']), 2) if not pd.isna(r['EMA_50']) else None,
                "rsi": round(float(r['RSI']), 1) if not pd.isna(r['RSI']) else None,
                "squeeze": bool(r['Squeeze_On']),
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
                "final_equity": res["final_equity"],
                "net_pnl": res["net_pnl"],
                "pnl_pct": res["pnl_pct"],
                "total_trades": res["total_trades"],
                "round_trips": res["round_trips"],
                "win_rate": res["win_rate"],
                "commission": res["commission"],
                "max_drawdown": res["max_drawdown"]
            },
            "ledger": res["ledger"],
            "candles": chart_candles,
            "markers": trade_markers,
            "equity_curve": res["equity_curve"],
            "patterns_log": patterns_log
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    print("启动 FastAPI 服务器于 http://127.0.0.1:8000 ...")
    uvicorn.run("main_api:app", host="127.0.0.1", port=8000, reload=True)
