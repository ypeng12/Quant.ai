// frontend/src/components/EquityCurve.tsx

import React, { useRef, useEffect } from 'react';
import { createChart, ColorType, LineStyle } from 'lightweight-charts';

interface DataPoint {
  time: number;
  value: number;
}

interface EquityCurveProps {
  equityCurve: DataPoint[];
  drawdownCurve: DataPoint[];
}

export const EquityCurve: React.FC<EquityCurveProps> = ({ equityCurve, drawdownCurve }) => {
  const equityChartRef = useRef<HTMLDivElement>(null);
  const drawdownChartRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!equityChartRef.current || equityCurve.length === 0) return;

    const chart = createChart(equityChartRef.current, {
      width: equityChartRef.current.clientWidth,
      height: 220,
      layout: {
        background: { type: ColorType.Solid, color: '#0a0a0a' },
        textColor: '#8e8e93',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.03)' },
        horzLines: { color: 'rgba(255,255,255,0.03)' },
      },
      timeScale: {
        borderColor: '#333',
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: '#333',
      },
      crosshair: {
        horzLine: { color: 'rgba(0,200,5,0.3)', style: LineStyle.Dashed },
        vertLine: { color: 'rgba(0,200,5,0.3)', style: LineStyle.Dashed },
      },
    });

    const series = chart.addLineSeries({
      color: '#00c805',
      lineWidth: 2,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });

    // Add initial equity baseline
    const initialValue = equityCurve.length > 0 ? equityCurve[0].value : 30000;
    
    const baselineSeries = chart.addLineSeries({
      color: 'rgba(142,142,147,0.4)',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });

    series.setData(equityCurve.map(d => ({
      time: d.time as any,
      value: d.value
    })));

    baselineSeries.setData([
      { time: equityCurve[0].time as any, value: initialValue },
      { time: equityCurve[equityCurve.length - 1].time as any, value: initialValue },
    ]);

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (equityChartRef.current) {
        chart.applyOptions({ width: equityChartRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [equityCurve]);

  useEffect(() => {
    if (!drawdownChartRef.current || drawdownCurve.length === 0) return;

    const chart = createChart(drawdownChartRef.current, {
      width: drawdownChartRef.current.clientWidth,
      height: 140,
      layout: {
        background: { type: ColorType.Solid, color: '#0a0a0a' },
        textColor: '#8e8e93',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.03)' },
        horzLines: { color: 'rgba(255,255,255,0.03)' },
      },
      timeScale: {
        borderColor: '#333',
        timeVisible: true,
      },
      rightPriceScale: {
        borderColor: '#333',
      },
      crosshair: {
        horzLine: { color: 'rgba(255,59,48,0.3)', style: LineStyle.Dashed },
        vertLine: { color: 'rgba(255,59,48,0.3)', style: LineStyle.Dashed },
      },
    });

    const areaSeries = chart.addAreaSeries({
      topColor: 'rgba(255, 59, 48, 0.0)',
      bottomColor: 'rgba(255, 59, 48, 0.15)',
      lineColor: '#ff3b30',
      lineWidth: 1,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
    });

    areaSeries.setData(drawdownCurve.map(d => ({
      time: d.time as any,
      value: d.value
    })));

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (drawdownChartRef.current) {
        chart.applyOptions({ width: drawdownChartRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [drawdownCurve]);

  if (equityCurve.length === 0) return null;

  // Quick stats
  const startVal = equityCurve[0]?.value ?? 0;
  const endVal = equityCurve[equityCurve.length - 1]?.value ?? 0;
  const change = endVal - startVal;
  const changePct = startVal > 0 ? (change / startVal * 100) : 0;
  const isUp = change >= 0;
  const minDD = drawdownCurve.length > 0 ? Math.min(...drawdownCurve.map(d => d.value)) : 0;

  return (
    <div className="card equity-curve-card">
      <div className="equity-curve-header">
        <h3 className="card-title">Equity & Drawdown Curve</h3>
        <div className="equity-curve-stats">
          <span className="equity-stat">
            Start: <strong>${startVal.toLocaleString(undefined, { maximumFractionDigits: 0 })}</strong>
          </span>
          <span className="equity-stat">
            End: <strong style={{ color: isUp ? 'var(--color-green)' : 'var(--color-red)' }}>
              ${endVal.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            </strong>
          </span>
          <span className="equity-stat" style={{ color: isUp ? 'var(--color-green)' : 'var(--color-red)' }}>
            {isUp ? '+' : ''}{changePct.toFixed(2)}%
          </span>
          <span className="equity-stat" style={{ color: 'var(--color-red)' }}>
            Max DD: {minDD.toFixed(2)}%
          </span>
        </div>
      </div>

      <div className="equity-chart-label">Account Equity ($)</div>
      <div ref={equityChartRef} className="equity-chart-container" />
      
      <div className="equity-chart-label" style={{ marginTop: '0.75rem' }}>Drawdown (%)</div>
      <div ref={drawdownChartRef} className="drawdown-chart-container" />
    </div>
  );
};
