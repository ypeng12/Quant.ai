# backend/app/risk_analyst.py
"""
AI Risk Analyst Module — Post-backtest analysis and risk report generation.
Analyzes drawdowns, regime performance, parameter sensitivity, transaction costs, and overfitting risk.
"""

import numpy as np


def generate_risk_report(backtest_result: dict, strategy_config: dict) -> dict:
    """
    Generate a comprehensive risk analysis report from backtest results.
    Returns structured JSON that includes both data points and natural language insights.
    """
    ticker = strategy_config.get("ticker", "UNKNOWN")
    interval = strategy_config.get("interval", "1d")
    strategy_mode = strategy_config.get("strategy_mode", "dynamic")
    
    summary = {
        "net_pnl": backtest_result.get("net_pnl", 0),
        "pnl_pct": backtest_result.get("pnl_pct", 0),
        "max_drawdown": backtest_result.get("max_drawdown", 0),
        "sharpe": backtest_result.get("sharpe", 0),
        "calmar": backtest_result.get("calmar", 0),
        "cagr": backtest_result.get("cagr", 0),
        "profit_factor": backtest_result.get("profit_factor", 0),
        "win_rate": backtest_result.get("win_rate", 0),
        "round_trips": backtest_result.get("round_trips", 0),
        "commission": backtest_result.get("commission", 0),
    }
    
    # Build analysis sections
    sections = []
    
    # 1. Performance Overview
    sections.append(_analyze_performance(summary, ticker, strategy_mode, interval))
    
    # 2. Risk Assessment
    sections.append(_analyze_risk(summary, backtest_result))
    
    # 3. Regime Analysis
    sections.append(_analyze_regimes(backtest_result))
    
    # 4. Transaction Cost Impact
    sections.append(_analyze_costs(summary, backtest_result))
    
    # 5. Strategy Recommendations
    sections.append(_generate_recommendations(summary, backtest_result, strategy_config))
    
    # Overall risk score (0-100, lower is riskier)
    risk_score = _compute_risk_score(summary)
    
    return {
        "ticker": ticker,
        "strategy": strategy_mode,
        "interval": interval,
        "risk_score": risk_score,
        "sections": sections,
        "key_metrics": summary,
    }


def _analyze_performance(summary, ticker, strategy, interval):
    """Analyze overall performance"""
    pnl = summary["net_pnl"]
    pnl_pct = summary["pnl_pct"]
    sharpe = summary["sharpe"]
    calmar = summary["calmar"]
    win_rate = summary["win_rate"]
    profit_factor = summary["profit_factor"]
    
    insights = []
    
    # PnL assessment
    if pnl > 0:
        insights.append(f"The {strategy} strategy on {ticker} ({interval}) generated a **positive return** of ${pnl:,.2f} ({pnl_pct:+.2f}%).")
    else:
        insights.append(f"The {strategy} strategy on {ticker} ({interval}) resulted in a **net loss** of ${pnl:,.2f} ({pnl_pct:+.2f}%). Consider revising parameters or strategy selection.")
    
    # Sharpe assessment
    if sharpe > 2.0:
        insights.append(f"Sharpe Ratio of {sharpe:.2f} is **excellent** — strong risk-adjusted returns.")
    elif sharpe > 1.0:
        insights.append(f"Sharpe Ratio of {sharpe:.2f} is **good** — above-average risk-adjusted performance.")
    elif sharpe > 0:
        insights.append(f"Sharpe Ratio of {sharpe:.2f} is **marginal** — returns barely compensate for volatility.")
    else:
        insights.append(f"Sharpe Ratio of {sharpe:.2f} is **negative** — the strategy underperformed risk-free rate.")
    
    # Win rate vs Profit Factor balance
    if win_rate > 60 and profit_factor > 1.5:
        insights.append(f"Win rate {win_rate:.1f}% with profit factor {profit_factor:.2f} indicates a **robust edge**.")
    elif win_rate < 40 and profit_factor < 1.0:
        insights.append(f"Low win rate ({win_rate:.1f}%) combined with profit factor below 1.0 ({profit_factor:.2f}) suggests **no statistical edge**.")
    elif win_rate < 45:
        if profit_factor > 1.5:
            insights.append(f"Despite low win rate ({win_rate:.1f}%), profit factor of {profit_factor:.2f} shows winners are significantly larger than losers — typical of trend-following systems.")
        else:
            insights.append(f"Win rate of {win_rate:.1f}% is below average. Consider tighter entry filters or regime-based filtering.")
    
    return {
        "title": "Performance Overview",
        "icon": "📊",
        "insights": insights,
        "severity": "positive" if pnl > 0 else "negative"
    }


def _analyze_risk(summary, backtest_result):
    """Analyze risk metrics"""
    max_dd = summary["max_drawdown"]
    calmar = summary["calmar"]
    insights = []
    
    # Max drawdown severity
    dd_pct = max_dd * 100
    if dd_pct > 20:
        insights.append(f"**⚠️ Critical**: Maximum drawdown reached **{dd_pct:.1f}%** — this exceeds institutional risk tolerance (typically 10-15%). A drawdown of this magnitude can be psychologically devastating and may trigger forced liquidation.")
    elif dd_pct > 10:
        insights.append(f"Maximum drawdown of **{dd_pct:.1f}%** is **elevated** but within acceptable bounds for aggressive strategies. The soft drawdown circuit breaker (7%) was likely triggered during this period.")
    elif dd_pct > 5:
        insights.append(f"Maximum drawdown of **{dd_pct:.1f}%** is **moderate** — well within the hard drawdown limit (12%).")
    else:
        insights.append(f"Maximum drawdown of **{dd_pct:.1f}%** is **minimal** — excellent capital preservation.")
    
    # Calmar assessment
    if calmar > 3:
        insights.append(f"Calmar Ratio of {calmar:.2f} is **outstanding** — return per unit of drawdown risk is very high.")
    elif calmar > 1:
        insights.append(f"Calmar Ratio of {calmar:.2f} is **acceptable** — return compensates for drawdown risk.")
    elif calmar > 0:
        insights.append(f"Calmar Ratio of {calmar:.2f} is **poor** — drawdown pain may not justify the returns.")
    
    # Consecutive loss analysis
    ledger = backtest_result.get("ledger", [])
    sell_trades = [t for t in ledger if t.get("action") == "SELL"]
    max_consecutive_loss = 0
    current_streak = 0
    for t in sell_trades:
        if t.get("realized_pnl", 0) < 0:
            current_streak += 1
            max_consecutive_loss = max(max_consecutive_loss, current_streak)
        else:
            current_streak = 0
    
    if max_consecutive_loss >= 5:
        insights.append(f"**⚠️ Warning**: Maximum consecutive losing streak was **{max_consecutive_loss} trades** — this would trigger the consecutive-loss risk reduction (threshold: 5).")
    elif max_consecutive_loss >= 3:
        insights.append(f"Maximum consecutive losing streak: {max_consecutive_loss} trades — within normal variance.")
    
    return {
        "title": "Risk Assessment",
        "icon": "🛡️",
        "insights": insights,
        "severity": "warning" if dd_pct > 10 else "positive"
    }


def _analyze_regimes(backtest_result):
    """Analyze performance across market regimes"""
    regime_breakdown = backtest_result.get("regime_breakdown", [])
    regime_distribution = backtest_result.get("regime_distribution", {})
    insights = []
    
    if not regime_breakdown:
        insights.append("No regime-specific trade data available. The strategy may not have generated trades across different market conditions.")
        return {
            "title": "Market Regime Analysis",
            "icon": "🚦",
            "insights": insights,
            "severity": "neutral"
        }
    
    # Identify best and worst performing regimes
    best_regime = max(regime_breakdown, key=lambda x: x["total_pnl"]) if regime_breakdown else None
    worst_regime = min(regime_breakdown, key=lambda x: x["total_pnl"]) if regime_breakdown else None
    
    if best_regime:
        insights.append(f"**Best performing regime**: `{best_regime['regime']}` — ${best_regime['total_pnl']:+,.2f} across {best_regime['trade_count']} trades ({best_regime['win_rate']:.0f}% win rate).")
    
    if worst_regime and worst_regime["total_pnl"] < 0:
        insights.append(f"**Worst performing regime**: `{worst_regime['regime']}` — ${worst_regime['total_pnl']:+,.2f} across {worst_regime['trade_count']} trades ({worst_regime['win_rate']:.0f}% win rate).")
    
    # Regime distribution context
    if regime_distribution:
        dominant_regime = max(regime_distribution.items(), key=lambda x: x[1])
        insights.append(f"Market spent **{dominant_regime[1]:.0f}%** of the time in `{dominant_regime[0]}` regime.")
    
    # Check for regime concentration risk
    for rb in regime_breakdown:
        if rb["trade_count"] == 0:
            continue
        if rb["win_rate"] < 30 and rb["trade_count"] >= 3:
            insights.append(f"**⚠️ Caution**: Strategy has only {rb['win_rate']:.0f}% win rate in `{rb['regime']}` regime — consider disabling trading in this market condition.")
    
    return {
        "title": "Market Regime Analysis",
        "icon": "🚦",
        "insights": insights,
        "severity": "neutral"
    }


def _analyze_costs(summary, backtest_result):
    """Analyze transaction cost impact"""
    commission = summary["commission"]
    gross_profit = backtest_result.get("gross_profit", 0)
    gross_loss = backtest_result.get("gross_loss", 0)
    net_pnl = summary["net_pnl"]
    round_trips = summary["round_trips"]
    insights = []
    
    # Commission as % of gross profit
    total_gross = gross_profit + abs(gross_loss) if gross_profit > 0 else 1
    commission_ratio = (commission / max(abs(net_pnl), 1)) * 100 if net_pnl != 0 else 0
    
    if commission > abs(net_pnl) and net_pnl > 0:
        insights.append(f"**⚠️ Critical**: Transaction costs (${commission:,.2f}) exceed net profit (${net_pnl:,.2f}) — the strategy may not survive real trading friction. Consider reducing trade frequency or increasing position hold time.")
    elif commission_ratio > 50:
        insights.append(f"Transaction costs consume **{commission_ratio:.0f}%** of net PnL — this is dangerously high. Each unnecessary round trip costs approximately ${commission/max(round_trips, 1):.2f}.")
    elif commission_ratio > 20:
        insights.append(f"Transaction costs account for **{commission_ratio:.0f}%** of net PnL (${commission:,.2f}) — moderate friction. Monitor cost sensitivity.")
    else:
        insights.append(f"Transaction costs (${commission:,.2f}) are **well-controlled** relative to performance — {commission_ratio:.0f}% of net PnL.")
    
    # Cost per round trip
    if round_trips > 0:
        cost_per_trip = commission / round_trips
        insights.append(f"Average cost per round trip: **${cost_per_trip:.2f}** (commission only, excluding slippage).")
    
    return {
        "title": "Transaction Cost Impact",
        "icon": "💰",
        "insights": insights,
        "severity": "warning" if commission_ratio > 50 else "positive"
    }


def _generate_recommendations(summary, backtest_result, strategy_config):
    """Generate actionable recommendations"""
    insights = []
    
    pnl = summary["net_pnl"]
    max_dd = summary["max_drawdown"]
    win_rate = summary["win_rate"]
    sharpe = summary["sharpe"]
    round_trips = summary["round_trips"]
    
    # Strategy-specific advice
    if round_trips == 0:
        insights.append("**No trades were executed** — the entry conditions may be too restrictive. Consider loosening RSI thresholds, reducing ADX trend requirements, or switching to a less filtered strategy mode.")
    elif round_trips < 3:
        insights.append(f"Only {round_trips} round trips — insufficient sample size for statistical significance. Extend the backtest period or test on additional tickers.")
    
    if pnl > 0 and sharpe > 0.5:
        insights.append("**Next steps**: Run walk-forward optimization to validate out-of-sample performance. Test parameter sensitivity by varying ATR multiplier ±0.5 and RSI threshold ±10.")
    
    if max_dd > 0.15:
        insights.append("**Risk reduction**: Consider lowering `risk_per_trade_pct` from current value or tightening the hard drawdown limit. A 15%+ drawdown on a $30K account means a $4,500 paper loss.")
    
    if win_rate < 40 and pnl < 0:
        insights.append("**Strategy pivot**: Low win rate with negative PnL suggests the strategy lacks edge in this market condition. Try: (1) switching to mean reversion in range-bound markets, (2) adding volume confirmation filters, or (3) testing on a different ticker with stronger trends.")
    
    if win_rate > 55 and pnl > 0:
        insights.append("**Overfitting warning**: High win rate + positive PnL should be validated out-of-sample. Run walk-forward optimization before trusting these results.")
    
    # Always recommend
    insights.append("**Standard validation checklist**: (1) Walk-forward optimization, (2) Cost stress test (2x-3x slippage), (3) Monte Carlo simulation of trade order, (4) Test on correlated but different tickers.")
    
    return {
        "title": "Recommendations & Next Steps",
        "icon": "🔬",
        "insights": insights,
        "severity": "neutral"
    }


def _compute_risk_score(summary):
    """
    Compute a composite risk score from 0-100 (higher = better/safer).
    """
    score = 50  # Start neutral
    
    # PnL contribution (±15)
    if summary["pnl_pct"] > 5:
        score += 15
    elif summary["pnl_pct"] > 0:
        score += 8
    elif summary["pnl_pct"] > -5:
        score -= 5
    else:
        score -= 15
    
    # Sharpe contribution (±15)
    if summary["sharpe"] > 2:
        score += 15
    elif summary["sharpe"] > 1:
        score += 10
    elif summary["sharpe"] > 0:
        score += 3
    else:
        score -= 10
    
    # Drawdown penalty (±10)
    dd_pct = summary["max_drawdown"] * 100
    if dd_pct < 5:
        score += 10
    elif dd_pct < 10:
        score += 5
    elif dd_pct > 20:
        score -= 15
    elif dd_pct > 15:
        score -= 10
    
    # Win rate contribution (±10)
    if summary["win_rate"] > 60:
        score += 10
    elif summary["win_rate"] > 45:
        score += 5
    elif summary["win_rate"] < 30:
        score -= 10
    
    return max(0, min(100, score))
