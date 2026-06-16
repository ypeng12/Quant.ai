// frontend/src/components/StockChart.tsx

import React, { useEffect, useRef } from 'react';
import { createChart, ColorType } from 'lightweight-charts';
import type { IChartApi, SeriesMarker, UTCTimestamp } from 'lightweight-charts';

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
  rsi: number | null;
  squeeze: boolean;
}

interface ChartMarker {
  time: number;
  position: 'aboveBar' | 'belowBar';
  color: string;
  shape: 'arrowUp' | 'arrowDown';
  text: string;
}

interface StockChartProps {
  candles: CandleData[];
  markers: ChartMarker[];
}

export const StockChart: React.FC<StockChartProps> = ({ candles, markers }) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [renderError, setRenderError] = React.useState<string | null>(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;
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
        height: 400,
        layout: {
          background: { type: ColorType.Solid, color: '#000000' },
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

      // 3. 添加指标折线序列
      // - VWAP (金黄色折线)
      const vwapSeries = chart.addLineSeries({
        color: '#ffd700',
        lineWidth: 2,
        title: 'VWAP',
        priceLineVisible: false,
      });

      // - EMA 9 (天蓝色面积图，用于突出短期动量)
      const ema9Series = chart.addAreaSeries({
        topColor: 'rgba(33, 150, 243, 0.15)',
        bottomColor: 'rgba(33, 150, 243, 0.0)',
        lineColor: '#2196f3',
        lineWidth: 1,
        title: 'EMA 9',
        priceLineVisible: false,
      });

      // - EMA 21 (橙色折线)
      const ema21Series = chart.addLineSeries({
        color: '#ff9800',
        lineWidth: 1,
        title: 'EMA 21',
        priceLineVisible: false,
      });

      // 4. 填充数据 (转换为 lightweight-charts 指定的类型)
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

      const ema21Data = candles
        .filter((c) => c.ema_21 !== null)
        .map((c) => ({ time: c.time as UTCTimestamp, value: c.ema_21 as number }));
      ema21Series.setData(ema21Data);

      // 5. 绑定买卖交易记录标记 (v4 稳定版原生 setMarkers)
      const chartMarkers: SeriesMarker<UTCTimestamp>[] = markers.map((m) => ({
        time: m.time as UTCTimestamp,
        position: m.position,
        color: m.color,
        shape: m.shape,
        text: m.text,
        size: 1.5,
      }));
      candlestickSeries.setMarkers(chartMarkers);

      // 自动缩放自适应数据范围
      chart.timeScale().fitContent();

      window.addEventListener('resize', handleResize);
    } catch (e: any) {
      console.error("Chart rendering error:", e);
      setRenderError(e.message || String(e));
    }

    // 清理资源
    return () => {
      window.removeEventListener('resize', handleResize);
      if (chart) {
        chart.remove();
      }
    };
  }, [candles, markers]);

  if (renderError) {
    return (
      <div className="loader-container" style={{ color: 'var(--color-red)', padding: '2rem', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <h4 style={{ margin: 0 }}>图表加载错误 (Chart Rendering Error)</h4>
        <div style={{ fontSize: '0.85rem', fontFamily: 'monospace', opacity: 0.8 }}>{renderError}</div>
      </div>
    );
  }

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      {/* 顶部指标图例指示器 */}
      <div
        style={{
          position: 'absolute',
          top: '10px',
          left: '10px',
          zIndex: 10,
          display: 'flex',
          gap: '12px',
          fontSize: '0.8rem',
          fontWeight: 600,
          pointerEvents: 'none',
        }}
      >
        <span style={{ color: '#ffd700' }}>● VWAP</span>
        <span style={{ color: '#2196f3' }}>● EMA 9</span>
        <span style={{ color: '#ff9800' }}>● EMA 21</span>
      </div>
      <div ref={chartContainerRef} style={{ width: '100%', height: '400px' }} />
    </div>
  );
};
