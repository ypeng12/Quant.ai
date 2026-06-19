// frontend/src/components/IntradayZoomChart.tsx

import React, { useEffect, useRef } from 'react';
import { createChart, ColorType } from 'lightweight-charts';
import type { IChartApi, SeriesMarker, UTCTimestamp } from 'lightweight-charts';
import type { LedgerItem } from './LedgerTable';

interface CandleData {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap: number | null;
  ema_9: number | null;
  ema_21: number | null;
  ema_50: number | null;
}

interface IntradayZoomChartProps {
  candles: CandleData[];
  tradeItem: LedgerItem;
  onClose: () => void;
}

export const IntradayZoomChart: React.FC<IntradayZoomChartProps> = ({ candles, tradeItem, onClose }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [renderError, setRenderError] = React.useState<string | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current || candles.length === 0) return;
    setRenderError(null);

    let chart: IChartApi | null = null;
    const handleResize = () => {
      if (chartContainerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: chartContainerRef.current.clientWidth,
        });
      }
    };

    try {
      // 1. 创建 TradingView 图表，设定 Robinhood 极简黑夜风样式
      chart = createChart(chartContainerRef.current, {
        width: chartContainerRef.current.clientWidth,
        height: 350,
        layout: {
          background: { type: ColorType.Solid, color: '#09090b' },
          textColor: '#8e8e93',
        },
        grid: {
          vertLines: { visible: false },
          horzLines: { visible: false },
        },
        timeScale: {
          timeVisible: true,
          secondsVisible: false,
          borderVisible: false,
        },
        rightPriceScale: {
          borderVisible: false,
        },
      });

      chartRef.current = chart;

      // 2. 添加 K 线蜡烛图系列
      const candlestickSeries = chart.addCandlestickSeries({
        upColor: '#00c805',
        downColor: '#ff3b30',
        borderDownColor: '#ff3b30',
        borderUpColor: '#00c805',
        wickDownColor: '#ff3b30',
        wickUpColor: '#00c805',
      });

      // 3. 添加均线序列
      const vwapSeries = chart.addLineSeries({
        color: '#ffd700',
        lineWidth: 2,
        title: 'VWAP',
        priceLineVisible: false,
      });

      const ema9Series = chart.addLineSeries({
        color: '#2196f3',
        lineWidth: 1,
        title: 'EMA 9',
        priceLineVisible: false,
      });

      // 4. 填充数据
      const candleData = candles.map((c) => ({
        time: c.time as UTCTimestamp,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));
      candlestickSeries.setData(candleData);

      const vwapData = candles
        .filter((c) => c.vwap !== null)
        .map((c) => ({ time: c.time as UTCTimestamp, value: c.vwap as number }));
      vwapSeries.setData(vwapData);

      const ema9Data = candles
        .filter((c) => c.ema_9 !== null)
        .map((c) => ({ time: c.time as UTCTimestamp, value: c.ema_9 as number }));
      ema9Series.setData(ema9Data);

      // 5. 绑定今日开盘 9:30 的模拟交易标记 (T+1 开盘价成交)
      // 我们寻找当天 09:30 AM EST 附近的 candle。如果没有正好 09:30 的，我们就用第一个 candle。
      let markerTime: UTCTimestamp = candles[0].time as UTCTimestamp;
      
      // 查找 09:30 的 K线。由于 Unix 时间戳可以转为当地小时分钟：
      // 在东部时间 09:30:00，我们可以计算第一个在 09:30 的时间戳：
      for (const c of candles) {
        const dateObj = new Date(c.time * 1000);
        // yfinance 历史分钟级数据在 US/Eastern 时区
        // 我们可以直接通过 toLocaleTimeString 或者 getUTCHours/getHours 检查
        // 由于 backend 传来的 time 已经是 Unix 时间戳
        // 对应美东时间 9:30 约为 UTC 时间 13:30 (标准时) 或 14:30 (夏令时)
        // 我们可以用本地小时检查，或者直接选择 9:30 标记
        const hour = dateObj.getHours();
        const min = dateObj.getMinutes();
        if (hour === 9 && min === 30) {
          markerTime = c.time as UTCTimestamp;
          break;
        }
      }

      const pnl = tradeItem.realized_pnl;
      const isBuy = tradeItem.action === 'BUY';
      const color = isBuy ? '#00c805' : (pnl !== undefined && pnl < 0 ? '#ff3b30' : '#00c805');
      const shape = isBuy ? 'arrowUp' : 'arrowDown';
      const position = isBuy ? 'belowBar' : 'aboveBar';
      const text = isBuy 
        ? `BUY ${tradeItem.shares}股 @ ${tradeItem.execution_price.toFixed(2)}` 
        : `SELL ${tradeItem.shares}股 @ ${tradeItem.execution_price.toFixed(2)} (${pnl !== undefined && pnl >= 0 ? '+' : ''}${pnl?.toFixed(2)})`;

      const chartMarkers: SeriesMarker<UTCTimestamp>[] = [{
        time: markerTime,
        position: position as any,
        color: color,
        shape: shape as any,
        text: text,
        size: 1.5,
      }];
      candlestickSeries.setMarkers(chartMarkers);

      // 自动缩放自适应数据范围
      chart.timeScale().fitContent();

      window.addEventListener('resize', handleResize);
    } catch (e: any) {
      console.error("Intraday chart rendering error:", e);
      setRenderError(e.message || String(e));
    }

    return () => {
      window.removeEventListener('resize', handleResize);
      if (chart) {
        chart.remove();
      }
    };
  }, [candles, tradeItem]);

  if (renderError) {
    return (
      <div className="loader-container" style={{ color: 'var(--color-red)', padding: '1rem', border: '1px dashed var(--color-border)' }}>
        <h4 style={{ margin: 0 }}>日内图表加载错误</h4>
        <div style={{ fontSize: '0.8rem', fontFamily: 'monospace' }}>{renderError}</div>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginTop: '1.5rem', border: '1px solid rgba(0, 200, 5, 0.3)', background: '#09090b' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <div>
          <h3 className="card-title" style={{ margin: 0 }}>🔍 日内交易 1分钟微观透视 (Intraday Trade Inspector)</h3>
          <span style={{ fontSize: '0.78rem', color: 'var(--color-text-secondary)' }}>
            标的：<strong style={{ color: '#fff' }}>{tradeItem.ticker}</strong> | 
            交易日期：<strong style={{ color: '#fff' }}>{tradeItem.timestamp.split(' ')[0]}</strong> | 
            成交动作：<strong style={{ color: tradeItem.action === 'BUY' ? 'var(--color-green)' : 'var(--color-red)' }}>
              {tradeItem.action === 'BUY' ? '买入' : '平仓'}
            </strong>
          </span>
        </div>
        <button 
          onClick={onClose} 
          style={{ 
            background: 'rgba(255,255,255,0.06)', 
            border: 'none', 
            color: '#fff', 
            borderRadius: '50%', 
            width: '26px', 
            height: '26px', 
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '0.9rem'
          }}
        >
          ✕
        </button>
      </div>

      <div style={{ position: 'relative', width: '100%' }}>
        <div
          style={{
            position: 'absolute',
            top: '8px',
            left: '10px',
            zIndex: 10,
            display: 'flex',
            gap: '12px',
            fontSize: '0.75rem',
            fontWeight: 600,
            pointerEvents: 'none',
          }}
        >
          <span style={{ color: '#ffd700' }}>● VWAP</span>
          <span style={{ color: '#2196f3' }}>● EMA 9</span>
        </div>
        <div ref={chartContainerRef} style={{ width: '100%', height: '350px' }} />
      </div>
    </div>
  );
};
