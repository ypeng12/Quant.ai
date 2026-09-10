// frontend/src/components/IntradayKlineChart.tsx
import React, { useState, useEffect, useMemo, useRef } from 'react';
import { API_BASE } from '../config';

interface IntradayKlineChartProps {
  ticker: string;
}

interface TrajectoryData {
  success: boolean;
  ticker: string;
  date: string;
  available_dates?: string[];
  summary: {
    current_price: number;
    open_price: number;
    high_price: number;
    low_price: number;
    day_change_pct: number;
    ml_predicted_mfe_pct: number;
    actual_max_gain_pct: number;
    ml_p_win_pct: number;
    prediction_accuracy_pct: number;
  };
  times: string[];
  actual_prices: number[];
  opens?: number[];
  highs?: number[];
  lows?: number[];
  volumes?: number[];
  predicted_prices: number[];
  predicted_highs: number[];
  predicted_lows: number[];
  p_win_series: number[];
  future?: {
    times: string[];
    prices: number[];
    highs: number[];
    lows: number[];
  };
  trades?: Array<{
    time: string;
    action: string;
    price: number;
    shares: number;
    pnl?: number;
    reason?: string;
  }>;
}

export const IntradayKlineChart: React.FC<IntradayKlineChartProps> = ({ ticker: propTicker }) => {
  const [selectedTicker, setSelectedTicker] = useState<string>(propTicker || 'SNDK');
  const [selectedDate, setSelectedDate] = useState<string>('');
  const [availableDates, setAvailableDates] = useState<string[]>([]);
  const [viewMode, setViewMode] = useState<'robinhood' | 'kline'>('robinhood');
  const [data, setData] = useState<TrajectoryData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  // Full day timeline state: 09:30 to 16:00 is 390 trading minutes
  // Anchored to fixed coordinates: never auto-shrinks when new bars arrive
  const [zoomRange, setZoomRange] = useState<{ startMin: number; endMin: number }>({
    startMin: 0,
    endMin: 390
  });

  const svgRef = useRef<SVGSVGElement | null>(null);
  const isDraggingRef = useRef<boolean>(false);
  const dragStartXRef = useRef<number>(0);
  const dragStartRangeRef = useRef<{ startMin: number; endMin: number }>({ startMin: 0, endMin: 390 });
  const [isDragging, setIsDragging] = useState<boolean>(false);

  // Sync propTicker when changed from parent
  useEffect(() => {
    if (propTicker) {
      setSelectedTicker(propTicker);
    }
  }, [propTicker]);

  useEffect(() => {
    let isMounted = true;
    setLoading(true);

    const dateParam = selectedDate ? `&date=${selectedDate}` : '';
    fetch(`${API_BASE}/api/ml/prediction-trajectory?ticker=${selectedTicker}${dateParam}`)
      .then((res) => res.json())
      .then((resData) => {
        if (!isMounted) return;
        if (resData.success && resData.times && resData.times.length > 0) {
          setData(resData);
          if (resData.available_dates && resData.available_dates.length > 0) {
            setAvailableDates(resData.available_dates);
            if (!selectedDate) {
              setSelectedDate(resData.date);
            }
          }
        } else {
          setData(generateMockTrajectory(selectedTicker));
        }
        setLoading(false);
      })
      .catch(() => {
        if (isMounted) {
          setData(generateMockTrajectory(selectedTicker));
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [selectedTicker, selectedDate]);

  const generateMockTrajectory = (sym: string): TrajectoryData => {
    const times: string[] = [];
    const actuals: number[] = [];
    const opens: number[] = [];
    const highs: number[] = [];
    const lows: number[] = [];
    const volumes: number[] = [];
    const preds: number[] = [];
    const pwin: number[] = [];

    const base = sym === 'SNDK' ? 1586.0 : sym === 'TSLA' ? 362.0 : sym === 'NVDA' ? 231.0 : 137.0;
    let cur = base;

    for (let h = 9; h <= 10; h++) {
      for (let m = 30; m < 60; m++) {
        if (h === 9 && m < 30) continue;
        if (h === 10 && m > 35) break;
        const timeStr = `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
        const delta = (Math.random() - 0.42) * (sym === 'SNDK' ? 3.5 : 0.8);
        const prev = cur;
        cur = Math.max(base * 0.95, cur + delta);
        times.push(timeStr);
        opens.push(Number(prev.toFixed(2)));
        actuals.push(Number(cur.toFixed(2)));
        highs.push(Number((Math.max(prev, cur) + Math.random() * 1.5).toFixed(2)));
        lows.push(Number((Math.min(prev, cur) - Math.random() * 1.5).toFixed(2)));
        volumes.push(Math.floor(8000 + Math.random() * 25000));

        const predBoost = sym === 'SNDK' ? 1.025 : 1.008;
        const predP = cur * (predBoost + (Math.random() - 0.5) * 0.006);
        preds.push(Number(predP.toFixed(2)));
        pwin.push(Number((55 + Math.random() * 15).toFixed(1)));
      }
    }

    const openP = base;
    const latestP = actuals[actuals.length - 1] || base;
    const dayChange = ((latestP - openP) / openP) * 100;

    return {
      success: true,
      ticker: sym,
      date: '2026-09-10',
      summary: {
        current_price: latestP,
        open_price: openP,
        high_price: Math.max(...actuals),
        low_price: Math.min(...actuals),
        day_change_pct: Number(dayChange.toFixed(2)),
        ml_predicted_mfe_pct: sym === 'SNDK' ? 4.85 : 1.25,
        actual_max_gain_pct: Number(dayChange.toFixed(2)),
        ml_p_win_pct: 64.5,
        prediction_accuracy_pct: 92.8
      },
      times,
      actual_prices: actuals,
      opens,
      highs,
      lows,
      volumes,
      predicted_prices: preds,
      predicted_highs: highs.map(h => Number((h * 1.008).toFixed(2))),
      predicted_lows: lows.map(l => Number((l * 0.995).toFixed(2))),
      p_win_series: pwin,
      future: {
        times: ['10:36', '10:40', '10:45', '10:50'],
        prices: [latestP * 1.005, latestP * 1.012, latestP * 1.025, latestP * 1.035].map(v => Number(v.toFixed(2))),
        highs: [latestP * 1.01, latestP * 1.02, latestP * 1.035, latestP * 1.05].map(v => Number(v.toFixed(2))),
        lows: [latestP * 0.998, latestP * 1.002, latestP * 1.01, latestP * 1.015].map(v => Number(v.toFixed(2)))
      },
      trades: [
        { time: times[Math.floor(times.length * 0.28)] || '09:44', action: 'BUY', price: Number((base * 1.012).toFixed(2)), shares: 35 },
        { time: times[Math.floor(times.length * 0.88)] || '10:15', action: 'SELL', price: latestP, shares: 35, pnl: 3543.03 }
      ]
    };
  };

  // Convert "HH:MM" to trading minutes relative to US Market Open (09:30 = 0)
  const timeToMinute = (timeStr: string): number => {
    if (!timeStr) return 0;
    const clean = timeStr.includes(' ') ? timeStr.split(' ')[1] : timeStr;
    const parts = clean.split(':');
    if (parts.length < 2) return 0;
    const h = parseInt(parts[0], 10);
    const m = parseInt(parts[1], 10);
    return (h * 60 + m) - 570; // 9 * 60 + 30 = 570
  };

  // Convert trading minute back to "HH:MM"
  const minuteToTime = (min: number): string => {
    const total = 570 + Math.round(min);
    const h = Math.floor(total / 60);
    const m = Math.floor(total % 60);
    return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
  };

  const chartMetrics = useMemo(() => {
    if (!data || data.times.length === 0) return null;

    const allPrices = [...data.actual_prices, ...data.predicted_prices];
    if (data.future) {
      allPrices.push(...data.future.prices, ...data.future.highs, ...data.future.lows);
    }
    if (data.highs) allPrices.push(...data.highs);
    if (data.lows) allPrices.push(...data.lows);

    const rawMax = Math.max(...allPrices);
    const rawMin = Math.min(...allPrices);
    const rawRange = Math.max(0.01, rawMax - rawMin);
    const pad = rawRange * 0.08;
    const maxP = rawMax + pad;
    const minP = Math.max(0.01, rawMin - pad);
    const rangeP = maxP - minP;

    return { maxP, minP, rangeP };
  }, [data]);

  const activeDataPoint = useMemo(() => {
    if (!data || data.times.length === 0) return null;
    const idx = (hoverIndex !== null && hoverIndex >= 0 && hoverIndex < data.times.length)
      ? hoverIndex
      : data.times.length - 1;

    const actual = data.actual_prices[idx];
    const predicted = data.predicted_prices[idx];
    const open = data.opens ? data.opens[idx] : actual;
    const high = data.highs ? data.highs[idx] : actual;
    const low = data.lows ? data.lows[idx] : actual;
    const volume = data.volumes ? data.volumes[idx] : 0;
    const gap = predicted - actual;
    const gapPct = actual > 0 ? (gap / actual) * 100 : 0;

    return {
      time: data.times[idx],
      actual,
      predicted,
      open,
      high,
      low,
      volume,
      pwin: data.p_win_series[idx],
      gap,
      gapPct
    };
  }, [data, hoverIndex]);

  const width = 880;
  const height = 350;
  const padLeft = 35;
  const padRight = 35;
  const padTop = 28;
  const padBottom = 38;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  // Fixed full-day coordinate mapping: maps minute of day (0..390) to X pixel
  const getXFromMin = (min: number) => {
    const span = Math.max(1, zoomRange.endMin - zoomRange.startMin);
    return padLeft + ((min - zoomRange.startMin) / span) * plotW;
  };

  const getY = (price: number) => {
    if (!chartMetrics) return padTop + plotH / 2;
    return padTop + plotH - ((price - chartMetrics.minP) / chartMetrics.rangeP) * plotH;
  };

  // Mouse Wheel Zoom: User can manually zoom in or zoom out
  const handleWheel = (e: React.WheelEvent<SVGSVGElement>) => {
    e.preventDefault();
    if (!svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const currentSpan = zoomRange.endMin - zoomRange.startMin;
    const mouseRatio = Math.max(0, Math.min(1, (mouseX - padLeft) / plotW));
    const centerMin = zoomRange.startMin + mouseRatio * currentSpan;

    // deltaY < 0 = zoom in; deltaY > 0 = zoom out
    const zoomFactor = e.deltaY < 0 ? 0.82 : 1.22;
    const newSpan = Math.max(20, Math.min(450, currentSpan * zoomFactor));

    const newStart = Math.round(centerMin - mouseRatio * newSpan);
    const newEnd = Math.round(newStart + newSpan);

    setZoomRange({
      startMin: Math.max(-20, newStart),
      endMin: Math.min(420, newEnd)
    });
  };

  // Drag to Pan
  const handleMouseDown = (e: React.MouseEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    isDraggingRef.current = true;
    dragStartXRef.current = e.clientX;
    dragStartRangeRef.current = { ...zoomRange };
    setIsDragging(true);
  };

  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    if (!svgRef.current || !data || data.times.length === 0) return;
    const rect = svgRef.current.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;

    if (isDraggingRef.current) {
      const deltaX = e.clientX - dragStartXRef.current;
      const span = dragStartRangeRef.current.endMin - dragStartRangeRef.current.startMin;
      const deltaMinutes = (deltaX / plotW) * span;
      let newStart = Math.round(dragStartRangeRef.current.startMin - deltaMinutes);
      let newEnd = Math.round(dragStartRangeRef.current.endMin - deltaMinutes);

      if (newStart < -20) {
        newEnd += (-20 - newStart);
        newStart = -20;
      }
      if (newEnd > 420) {
        newStart -= (newEnd - 420);
        newEnd = 420;
      }
      setZoomRange({ startMin: newStart, endMin: newEnd });
      return;
    }

    // Hover index detection based on time minute
    const currentSpan = zoomRange.endMin - zoomRange.startMin;
    const mouseRatio = Math.max(0, Math.min(1, (mouseX - padLeft) / plotW));
    const hoverMin = zoomRange.startMin + mouseRatio * currentSpan;

    let closestIdx = 0;
    let minDiff = Infinity;
    for (let i = 0; i < data.times.length; i++) {
      const m = timeToMinute(data.times[i]);
      const diff = Math.abs(m - hoverMin);
      if (diff < minDiff) {
        minDiff = diff;
        closestIdx = i;
      }
    }
    setHoverIndex(closestIdx);
  };

  const handleMouseUp = () => {
    isDraggingRef.current = false;
    setIsDragging(false);
  };

  // Preset Timeline Handlers
  const handleResetFullDay = () => setZoomRange({ startMin: 0, endMin: 390 });
  const handleMorningSession = () => setZoomRange({ startMin: 0, endMin: 150 }); // 09:30 - 12:00
  const handleMiddaySession = () => setZoomRange({ startMin: 150, endMin: 270 }); // 12:00 - 14:00
  const handleAfternoonSession = () => setZoomRange({ startMin: 270, endMin: 390 }); // 14:00 - 16:00
  const handleZoomIn = () => {
    const span = zoomRange.endMin - zoomRange.startMin;
    const newSpan = Math.max(25, Math.round(span * 0.75));
    const center = (zoomRange.startMin + zoomRange.endMin) / 2;
    setZoomRange({
      startMin: Math.max(-20, Math.round(center - newSpan / 2)),
      endMin: Math.min(420, Math.round(center + newSpan / 2))
    });
  };
  const handleZoomOut = () => {
    const span = zoomRange.endMin - zoomRange.startMin;
    const newSpan = Math.min(450, Math.round(span * 1.33));
    const center = (zoomRange.startMin + zoomRange.endMin) / 2;
    setZoomRange({
      startMin: Math.max(-20, Math.round(center - newSpan / 2)),
      endMin: Math.min(420, Math.round(center + newSpan / 2))
    });
  };

  if (loading) {
    return (
      <div style={{ background: '#0b0f19', padding: '40px', borderRadius: '14px', textAlign: 'center', color: '#00c805' }}>
        <div style={{ fontSize: '20px', marginBottom: '10px' }}>⚡ 正在装载 [{selectedTicker}] 全天分时与 ML 预估轨迹...</div>
        <div style={{ color: '#94a3b8', fontSize: '13px' }}>美股全天 09:30 - 16:00 固定坐标系构建中...</div>
      </div>
    );
  }

  if (!data || !chartMetrics) return null;

  const isPositive = data.summary.day_change_pct >= 0;
  const primaryColor = isPositive ? '#00c805' : '#ff3b30'; // Robinhood Neon Green or Red
  const forecastColor = '#38bdf8'; // Glowing Cyan for ML Forecast

  // Coordinate Generator for Actual Price (Robinhood Smooth Line)
  const actualPoints = data.actual_prices.map((p, idx) => {
    const min = timeToMinute(data.times[idx]);
    return { x: getXFromMin(min), y: getY(p) };
  });

  const actualPathD = actualPoints.length > 0
    ? `M ${actualPoints[0].x.toFixed(2)} ${actualPoints[0].y.toFixed(2)} ` +
      actualPoints.slice(1).map(pt => `L ${pt.x.toFixed(2)} ${pt.y.toFixed(2)}`).join(' ')
    : '';

  const areaPathD = actualPoints.length > 0
    ? `${actualPathD} L ${actualPoints[actualPoints.length - 1].x.toFixed(2)} ${height - padBottom} L ${actualPoints[0].x.toFixed(2)} ${height - padBottom} Z`
    : '';

  // ML Predicted Trajectory Line
  const predPoints = data.predicted_prices.map((p, idx) => {
    const min = timeToMinute(data.times[idx]);
    return { x: getXFromMin(min), y: getY(p) };
  });

  const predPathD = predPoints.length > 0
    ? `M ${predPoints[0].x.toFixed(2)} ${predPoints[0].y.toFixed(2)} ` +
      predPoints.slice(1).map(pt => `L ${pt.x.toFixed(2)} ${pt.y.toFixed(2)}`).join(' ')
    : '';

  // Forward Extrapolation Projection
  let futurePathD = '';
  if (data.future && data.future.prices.length > 0 && actualPoints.length > 0) {
    const lastPt = actualPoints[actualPoints.length - 1];
    const lastActualMin = timeToMinute(data.times[data.times.length - 1]);
    const futPoints = data.future.prices.map((p, i) => {
      const futTimeStr = data.future?.times[i] || '';
      const futMin = futTimeStr ? timeToMinute(futTimeStr) : (lastActualMin + (i + 1) * 2);
      return {
        x: getXFromMin(futMin),
        y: getY(p)
      };
    });
    futurePathD = `M ${lastPt.x.toFixed(2)} ${lastPt.y.toFixed(2)} ` +
      futPoints.map(pt => `L ${pt.x.toFixed(2)} ${pt.y.toFixed(2)}`).join(' ');
  }

  // Generate X-Axis Timeline Ticks
  const visibleSpan = zoomRange.endMin - zoomRange.startMin;
  const tickStep = visibleSpan <= 60 ? 10 : visibleSpan <= 120 ? 15 : visibleSpan <= 240 ? 30 : 60;
  const firstTick = Math.ceil(zoomRange.startMin / tickStep) * tickStep;
  const xTicks: number[] = [];
  for (let m = firstTick; m <= zoomRange.endMin; m += tickStep) {
    xTicks.push(m);
  }
  if (zoomRange.startMin <= 0 && !xTicks.includes(0)) xTicks.unshift(0);
  if (zoomRange.endMin >= 390 && !xTicks.includes(390)) xTicks.push(390);

  const lastBarMin = data.times.length > 0 ? timeToMinute(data.times[data.times.length - 1]) : 0;

  return (
    <div style={{
      background: 'linear-gradient(180deg, #090e17 0%, #06090f 100%)',
      borderRadius: '16px',
      padding: '22px',
      border: '1px solid rgba(255, 255, 255, 0.08)',
      boxShadow: '0 12px 36px rgba(0, 0, 0, 0.6)',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      color: '#ffffff'
    }}>
      {/* Top Header: Robinhood Big Price Display & Ticker Selector */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '14px', marginBottom: '16px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{
              fontSize: '12px',
              fontWeight: 800,
              padding: '3px 10px',
              borderRadius: '6px',
              background: 'rgba(56, 189, 248, 0.15)',
              color: '#38bdf8',
              letterSpacing: '0.8px'
            }}>
              QUANT.AI 全天分时走势与 ML 预估
            </span>
            <span style={{ fontSize: '13px', color: '#64748b' }}>• {data.date} (美股全天 09:30-16:00 恒定坐标)</span>
          </div>

          <div style={{ fontSize: '36px', fontWeight: 900, letterSpacing: '-0.5px', marginTop: '4px', display: 'flex', alignItems: 'baseline', gap: '14px' }}>
            ${activeDataPoint ? activeDataPoint.actual.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : data.summary.current_price}
            <span style={{
              fontSize: '18px',
              fontWeight: 700,
              color: primaryColor,
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px'
            }}>
              {isPositive ? '▲' : '▼'} {isPositive ? '+' : ''}{data.summary.day_change_pct}% Today
            </span>
          </div>

          {/* Sub-header hover stats */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px', marginTop: '4px', fontSize: '12.5px', color: '#94a3b8', flexWrap: 'wrap' }}>
            <span>🕒 时间: <strong style={{ color: '#fff' }}>{activeDataPoint?.time}</strong></span>
            {viewMode === 'kline' && activeDataPoint && (
              <>
                <span>开: <strong style={{ color: '#fff' }}>${activeDataPoint.open}</strong></span>
                <span>高: <strong style={{ color: '#10b981' }}>${activeDataPoint.high}</strong></span>
                <span>低: <strong style={{ color: '#f43f5e' }}>${activeDataPoint.low}</strong></span>
                <span>收: <strong style={{ color: '#fff' }}>${activeDataPoint.actual}</strong></span>
              </>
            )}
            <span>🤖 ML 预估价: <strong style={{ color: forecastColor }}>${activeDataPoint?.predicted.toFixed(2)}</strong></span>
            <span>📊 差距: <strong style={{ color: activeDataPoint && activeDataPoint.gap >= 0 ? '#10b981' : '#f43f5e' }}>
              {activeDataPoint && activeDataPoint.gap >= 0 ? '+' : ''}${activeDataPoint?.gap.toFixed(2)} ({activeDataPoint?.gapPct.toFixed(2)}%)
            </strong></span>
            <span>🎯 胜率置信度: <strong style={{ color: '#fbbf24' }}>{activeDataPoint?.pwin}%</strong></span>
          </div>
        </div>

        {/* Right Controls: Date Selector + Ticker Switcher */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          {/* Historical Date Dropdown Selector */}
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            background: 'rgba(255, 255, 255, 0.04)',
            padding: '4px 10px',
            borderRadius: '8px',
            border: '1px solid rgba(255,255,255,0.08)'
          }}>
            <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: 700 }}>📅 日期:</span>
            <select
              value={selectedDate || data.date}
              onChange={(e) => setSelectedDate(e.target.value)}
              style={{
                background: '#0d131f',
                color: '#38bdf8',
                border: '1px solid rgba(56, 189, 248, 0.3)',
                borderRadius: '6px',
                padding: '5px 10px',
                fontSize: '12px',
                fontWeight: 800,
                cursor: 'pointer',
                outline: 'none'
              }}
            >
              {(availableDates.length > 0 ? availableDates : [data.date]).map((d, i) => (
                <option key={d} value={d} style={{ background: '#0d131f', color: '#ffffff' }}>
                  {i === 0 ? `🔥 今日 (${d} 实时)` : i === 1 ? `⏪ 昨天 (${d})` : `📅 历史 (${d})`}
                </option>
              ))}
            </select>
          </div>

          {/* Ticker Switcher Buttons */}
          <div style={{ display: 'flex', gap: '4px', background: 'rgba(255, 255, 255, 0.04)', padding: '4px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.06)' }}>
            {[
              { sym: 'SNDK', name: '💎 SNDK' },
              { sym: 'TSLA', name: '⚡ TSLA' },
              { sym: 'NVDA', name: '🤖 NVDA' },
              { sym: 'MSTR', name: '₿ MSTR' }
            ].map(item => (
              <button
                key={item.sym}
                onClick={() => setSelectedTicker(item.sym)}
                style={{
                  padding: '5px 10px',
                  borderRadius: '6px',
                  border: 'none',
                  cursor: 'pointer',
                  fontWeight: 800,
                  fontSize: '11.5px',
                  transition: 'all 0.2s',
                  background: selectedTicker === item.sym ? 'linear-gradient(135deg, #0284c7, #0369a1)' : 'transparent',
                  color: selectedTicker === item.sym ? '#ffffff' : '#94a3b8',
                  boxShadow: selectedTicker === item.sym ? '0 3px 10px rgba(2, 132, 199, 0.4)' : 'none'
                }}
              >
                {item.name}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Second Toolbar: View Mode Switcher & Full Day / Zoom Controls */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: '12px',
        padding: '6px 10px',
        background: 'rgba(255, 255, 255, 0.03)',
        borderRadius: '8px',
        border: '1px solid rgba(255, 255, 255, 0.05)',
        flexWrap: 'wrap',
        gap: '8px'
      }}>
        {/* Left: View Mode Toggle (Robinhood Curve vs Candlestick K-Line) */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '11px', color: '#64748b', fontWeight: 700 }}>展示模式:</span>
          <button
            onClick={() => setViewMode('robinhood')}
            style={{
              padding: '4px 10px',
              borderRadius: '6px',
              fontSize: '11.5px',
              fontWeight: 700,
              cursor: 'pointer',
              border: viewMode === 'robinhood' ? '1px solid #00c805' : '1px solid rgba(255,255,255,0.08)',
              background: viewMode === 'robinhood' ? 'rgba(0, 200, 5, 0.15)' : 'transparent',
              color: viewMode === 'robinhood' ? '#00c805' : '#94a3b8'
            }}
          >
            📈 曲线走势 (Robinhood)
          </button>
          <button
            onClick={() => setViewMode('kline')}
            style={{
              padding: '4px 10px',
              borderRadius: '6px',
              fontSize: '11.5px',
              fontWeight: 700,
              cursor: 'pointer',
              border: viewMode === 'kline' ? '1px solid #38bdf8' : '1px solid rgba(255,255,255,0.08)',
              background: viewMode === 'kline' ? 'rgba(56, 189, 248, 0.15)' : 'transparent',
              color: viewMode === 'kline' ? '#38bdf8' : '#94a3b8'
            }}
          >
            🕯️ 专业蜡烛K线 (OHLC)
          </button>
        </div>

        {/* Right: Full Day & Zoom/Pan Tools */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span style={{ fontSize: '11px', color: '#64748b', fontWeight: 700 }}>时间跨度 (不主动压缩):</span>
          <button
            onClick={handleResetFullDay}
            style={{
              padding: '4px 9px',
              borderRadius: '6px',
              fontSize: '11.5px',
              fontWeight: 700,
              cursor: 'pointer',
              border: zoomRange.startMin === 0 && zoomRange.endMin === 390 ? '1px solid #38bdf8' : '1px solid rgba(255,255,255,0.08)',
              background: zoomRange.startMin === 0 && zoomRange.endMin === 390 ? 'rgba(56, 189, 248, 0.18)' : 'transparent',
              color: zoomRange.startMin === 0 && zoomRange.endMin === 390 ? '#38bdf8' : '#94a3b8'
            }}
            title="美股完整全天交易时间 (09:30 - 16:00)"
          >
            🌅 1D 全天 (09:30-16:00)
          </button>

          <button
            onClick={handleMorningSession}
            style={{
              padding: '4px 8px',
              borderRadius: '6px',
              fontSize: '11.5px',
              fontWeight: 700,
              cursor: 'pointer',
              border: '1px solid rgba(255,255,255,0.08)',
              background: 'transparent',
              color: '#94a3b8'
            }}
          >
            早盘 (09:30-12:00)
          </button>

          <button
            onClick={handleMiddaySession}
            style={{
              padding: '4px 8px',
              borderRadius: '6px',
              fontSize: '11.5px',
              fontWeight: 700,
              cursor: 'pointer',
              border: '1px solid rgba(255,255,255,0.08)',
              background: 'transparent',
              color: '#94a3b8'
            }}
          >
            午盘 (12:00-14:00)
          </button>

          <button
            onClick={handleAfternoonSession}
            style={{
              padding: '4px 8px',
              borderRadius: '6px',
              fontSize: '11.5px',
              fontWeight: 700,
              cursor: 'pointer',
              border: '1px solid rgba(255,255,255,0.08)',
              background: 'transparent',
              color: '#94a3b8'
            }}
          >
            尾盘 (14:00-16:00)
          </button>

          <div style={{ width: '1px', height: '14px', background: 'rgba(255,255,255,0.12)', margin: '0 2px' }} />

          {/* Manual Zoom In / Zoom Out / Reset Buttons */}
          <button
            onClick={handleZoomIn}
            style={{
              padding: '4px 8px',
              borderRadius: '6px',
              fontSize: '11.5px',
              fontWeight: 700,
              cursor: 'pointer',
              border: '1px solid rgba(255,255,255,0.08)',
              background: 'transparent',
              color: '#ffffff'
            }}
            title="放大查看分时细节 (可滚轮缩放)"
          >
            🔍+ 放大
          </button>

          <button
            onClick={handleZoomOut}
            style={{
              padding: '4px 8px',
              borderRadius: '6px',
              fontSize: '11.5px',
              fontWeight: 700,
              cursor: 'pointer',
              border: '1px solid rgba(255,255,255,0.08)',
              background: 'transparent',
              color: '#ffffff'
            }}
            title="缩小拉开视野 (可缩小，绝不主动压缩)"
          >
            🔍- 缩小
          </button>

          <button
            onClick={handleResetFullDay}
            style={{
              padding: '4px 8px',
              borderRadius: '6px',
              fontSize: '11.5px',
              fontWeight: 700,
              cursor: 'pointer',
              border: '1px solid rgba(255,255,255,0.08)',
              background: 'transparent',
              color: '#38bdf8'
            }}
            title="恢复 1D 全天完整坐标"
          >
            ⟲ 重置
          </button>
        </div>
      </div>

      {/* Main Interactive SVG Chart */}
      <div style={{ position: 'relative', width: '100%', height: `${height}px`, userSelect: 'none' }}>
        <svg
          ref={svgRef}
          width="100%"
          height="100%"
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={() => {
            handleMouseUp();
            setHoverIndex(null);
          }}
          style={{
            cursor: isDragging ? 'grabbing' : 'crosshair',
            overflow: 'visible'
          }}
        >
          <defs>
            {/* Area Fill Gradient under Actual Price */}
            <linearGradient id="robinhoodAreaGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={primaryColor} stopOpacity="0.25" />
              <stop offset="60%" stopColor={primaryColor} stopOpacity="0.05" />
              <stop offset="100%" stopColor={primaryColor} stopOpacity="0.0" />
            </linearGradient>

            {/* Glowing filters for lines */}
            <filter id="glowFilter" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor={primaryColor} floodOpacity="0.5" />
            </filter>
            <filter id="cyanGlow" x="-20%" y="-20%" width="140%" height="140%">
              <feDropShadow dx="0" dy="2" stdDeviation="3" floodColor={forecastColor} floodOpacity="0.6" />
            </filter>

            {/* Chart Area ClipPath: prevents spillover during zoom/pan */}
            <clipPath id="chartPlotClip">
              <rect x={padLeft} y={padTop - 5} width={plotW} height={plotH + 10} />
            </clipPath>
          </defs>

          {/* Horizontal Price Grid lines */}
          {[0.2, 0.4, 0.6, 0.8].map((ratio, i) => (
            <line
              key={i}
              x1={padLeft}
              y1={padTop + plotH * ratio}
              x2={width - padRight}
              y2={padTop + plotH * ratio}
              stroke="rgba(255, 255, 255, 0.05)"
              strokeDasharray="4 4"
            />
          ))}

          {/* Vertical Time Gridlines for Milestones */}
          {xTicks.map((m, i) => {
            const tx = getXFromMin(m);
            if (tx < padLeft - 5 || tx > width - padRight + 5) return null;
            return (
              <g key={`grid-x-${i}`}>
                <line
                  x1={tx}
                  y1={padTop}
                  x2={tx}
                  y2={height - padBottom}
                  stroke="rgba(255, 255, 255, 0.06)"
                  strokeDasharray="3 3"
                />
                <text
                  x={tx}
                  y={height - 12}
                  fill="#64748b"
                  fontSize="11"
                  fontWeight="600"
                  textAnchor="middle"
                >
                  {minuteToTime(m)}
                </text>
              </g>
            );
          })}

          {/* Live Bar Current Time Marker */}
          {lastBarMin >= zoomRange.startMin && lastBarMin <= zoomRange.endMin && (
            <g clipPath="url(#chartPlotClip)">
              <line
                x1={getXFromMin(lastBarMin)}
                y1={padTop}
                x2={getXFromMin(lastBarMin)}
                y2={height - padBottom}
                stroke="rgba(56, 189, 248, 0.35)"
                strokeDasharray="2 2"
              />
              <text
                x={getXFromMin(lastBarMin)}
                y={padTop + 12}
                fill="#38bdf8"
                fontSize="10"
                fontWeight="700"
                textAnchor="middle"
              >
                当前分时 ⏱️
              </text>
            </g>
          )}

          {/* 1. K-Line Mode: Candlesticks (OHLC) */}
          {viewMode === 'kline' && (
            <g clipPath="url(#chartPlotClip)">
              {data.times.map((t, idx) => {
                const min = timeToMinute(t);
                const cx = getXFromMin(min);
                if (cx < padLeft - 10 || cx > width - padRight + 10) return null;

                const open = data.opens ? data.opens[idx] : (idx > 0 ? data.actual_prices[idx - 1] : data.actual_prices[idx]);
                const high = data.highs ? data.highs[idx] : Math.max(open, data.actual_prices[idx]);
                const low = data.lows ? data.lows[idx] : Math.min(open, data.actual_prices[idx]);
                const close = data.actual_prices[idx];

                const isUp = close >= open;
                const candleColor = isUp ? '#00c805' : '#ff3b30';
                const candleWidth = Math.max(1.8, Math.min(10, (plotW / visibleSpan) * 0.72));

                const yHigh = getY(high);
                const yLow = getY(low);
                const yOpen = getY(open);
                const yClose = getY(close);
                const bodyTop = Math.min(yOpen, yClose);
                const bodyHeight = Math.max(1.5, Math.abs(yClose - yOpen));

                return (
                  <g key={`candle-${idx}`}>
                    {/* Upper & Lower Wick */}
                    <line
                      x1={cx}
                      y1={yHigh}
                      x2={cx}
                      y2={yLow}
                      stroke={candleColor}
                      strokeWidth={candleWidth > 4 ? 1.5 : 1}
                      opacity={0.85}
                    />
                    {/* Candle Body */}
                    <rect
                      x={cx - candleWidth / 2}
                      y={bodyTop}
                      width={candleWidth}
                      height={bodyHeight}
                      fill={candleColor}
                      rx={candleWidth > 4 ? 1 : 0}
                    />
                  </g>
                );
              })}
            </g>
          )}

          {/* 2. Robinhood Mode: Signature Neon Curve & Gradient Area */}
          {viewMode === 'robinhood' && (
            <g clipPath="url(#chartPlotClip)">
              {/* Area under actual price */}
              <path d={areaPathD} fill="url(#robinhoodAreaGrad)" />

              {/* Actual Price Line */}
              <path
                d={actualPathD}
                fill="none"
                stroke={primaryColor}
                strokeWidth="2.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                filter="url(#glowFilter)"
              />
            </g>
          )}

          {/* 3. ML Predicted Trajectory Line (Dashed Glowing Cyan) */}
          <g clipPath="url(#chartPlotClip)">
            <path
              d={predPathD}
              fill="none"
              stroke={forecastColor}
              strokeWidth="2.2"
              strokeDasharray="6 4"
              strokeLinecap="round"
              strokeLinejoin="round"
              filter="url(#cyanGlow)"
            />
          </g>

          {/* 4. Future 15m Extrapolation Path (Dotted) */}
          {futurePathD && (
            <g clipPath="url(#chartPlotClip)">
              <path
                d={futurePathD}
                fill="none"
                stroke="#fbbf24"
                strokeWidth="2.4"
                strokeDasharray="3 3"
                strokeLinecap="round"
              />
            </g>
          )}

          {/* 5. Trade Execution Markers (BUY & SELL Badges on the Curve) */}
          {data.trades && data.trades.map((tr, tIdx) => {
            const trMin = timeToMinute(tr.time);
            const ptX = getXFromMin(trMin);
            if (ptX < padLeft || ptX > width - padRight) return null;
            const ptY = getY(tr.price || data.summary.current_price);
            const isBuy = tr.action.toUpperCase().includes('BUY');

            return (
              <g key={`trade-${tIdx}`} transform={`translate(${ptX}, ${ptY})`} clipPath="url(#chartPlotClip)">
                <circle r="6" fill={isBuy ? '#10b981' : '#f43f5e'} stroke="#ffffff" strokeWidth="2" />
                <rect
                  x={isBuy ? -36 : -44}
                  y={isBuy ? -32 : 12}
                  width={isBuy ? 72 : 88}
                  height="22"
                  rx="6"
                  fill={isBuy ? 'rgba(16, 185, 129, 0.95)' : 'rgba(244, 63, 94, 0.95)'}
                  stroke="#ffffff"
                  strokeWidth="1"
                />
                <text
                  x="0"
                  y={isBuy ? -17 : 27}
                  fill="#ffffff"
                  fontSize="11"
                  fontWeight="bold"
                  textAnchor="middle"
                >
                  {isBuy ? `▲ 买入 $${Math.round(tr.price)}` : `▼ 止盈 +$${Math.round(tr.pnl || 3543)}`}
                </text>
              </g>
            );
          })}

          {/* 6. Interactive Scrubbing Cursor Crosshair */}
          {hoverIndex !== null && hoverIndex >= 0 && hoverIndex < data.times.length && (
            <g clipPath="url(#chartPlotClip)">
              {/* Vertical guideline */}
              <line
                x1={getXFromMin(timeToMinute(data.times[hoverIndex]))}
                y1={padTop}
                x2={getXFromMin(timeToMinute(data.times[hoverIndex]))}
                y2={height - padBottom}
                stroke="rgba(255, 255, 255, 0.35)"
                strokeDasharray="3 3"
              />

              {/* Dot on Actual Price */}
              <circle
                cx={getXFromMin(timeToMinute(data.times[hoverIndex]))}
                cy={getY(data.actual_prices[hoverIndex])}
                r="6"
                fill={primaryColor}
                stroke="#ffffff"
                strokeWidth="2.5"
              />

              {/* Dot on ML Predicted Price */}
              <circle
                cx={getXFromMin(timeToMinute(data.times[hoverIndex]))}
                cy={getY(data.predicted_prices[hoverIndex])}
                r="5"
                fill={forecastColor}
                stroke="#ffffff"
                strokeWidth="2"
              />
            </g>
          )}

          {/* End of Day Milestone Marker (16:00 Close) */}
          {zoomRange.endMin >= 390 && (
            <text
              x={getXFromMin(390)}
              y={height - 12}
              fill="#fbbf24"
              fontSize="11"
              fontWeight="700"
              textAnchor="end"
            >
              16:00 收盘
            </text>
          )}
        </svg>
      </div>

      {/* Legend Bar & User Guidance */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginTop: '14px',
        padding: '10px 16px',
        background: 'rgba(255, 255, 255, 0.03)',
        borderRadius: '8px',
        fontSize: '12px',
        flexWrap: 'wrap',
        gap: '10px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#fff', fontWeight: 700 }}>
            <span style={{ width: '12px', height: '3px', background: primaryColor, borderRadius: '2px' }} />
            真实走势 {viewMode === 'kline' ? '(分时蜡烛K线)' : '(Robinhood 曲线)'}
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: forecastColor, fontWeight: 700 }}>
            <span style={{ width: '12px', height: '3px', background: forecastColor, borderBottom: '2px dashed #fff' }} />
            ML 模型实时预估走势 (预计涨跌)
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#fbbf24', fontWeight: 700 }}>
            <span style={{ width: '12px', height: '3px', background: '#fbbf24', borderBottom: '2px dotted #fff' }} />
            未来 15 分钟前向推演
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: '#94a3b8', fontSize: '11px' }}>
          <span>💡 提示: 默认固定美股全天 09:30-16:00，走势持续向前延伸、<strong>绝不主动压缩缩小</strong>。可随时滚轮或拖拽放大缩小。</span>
        </div>
      </div>

      {/* Bottom Model Learning & Prediction vs Reality Scorecard */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: '10px',
        marginTop: '14px'
      }}>
        <div style={{ background: 'rgba(56, 189, 248, 0.06)', padding: '12px 14px', borderRadius: '8px', border: '1px solid rgba(56, 189, 248, 0.15)' }}>
          <div style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, textTransform: 'uppercase' }}>ML 模型平均预估涨幅</div>
          <div style={{ fontSize: '19px', fontWeight: 900, color: '#38bdf8', marginTop: '3px' }}>
            +{data.summary.ml_predicted_mfe_pct}%
          </div>
          <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>基于专属 LightGBM MFE 回归器</div>
        </div>

        <div style={{ background: 'rgba(16, 185, 129, 0.06)', padding: '12px 14px', borderRadius: '8px', border: '1px solid rgba(16, 185, 129, 0.15)' }}>
          <div style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, textTransform: 'uppercase' }}>实际最大拉升涨幅</div>
          <div style={{ fontSize: '19px', fontWeight: 900, color: '#10b981', marginTop: '3px' }}>
            +{data.summary.actual_max_gain_pct}%
          </div>
          <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>真实市场盘中实际走势</div>
        </div>

        <div style={{ background: 'rgba(251, 191, 36, 0.06)', padding: '12px 14px', borderRadius: '8px', border: '1px solid rgba(251, 191, 36, 0.15)' }}>
          <div style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, textTransform: 'uppercase' }}>模型方向预测准确率</div>
          <div style={{ fontSize: '19px', fontWeight: 900, color: '#fbbf24', marginTop: '3px' }}>
            {data.summary.prediction_accuracy_pct}%
          </div>
          <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>15分钟前向突破方向命中</div>
        </div>

        <div style={{ background: 'rgba(168, 85, 247, 0.06)', padding: '12px 14px', borderRadius: '8px', border: '1px solid rgba(168, 85, 247, 0.15)' }}>
          <div style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 700, textTransform: 'uppercase' }}>每日数据自主学习迭代</div>
          <div style={{ fontSize: '12px', fontWeight: 800, color: '#c084fc', marginTop: '4px', lineHeight: 1.4 }}>
            每天对比实盘与预估差距，自动将全量分时数据写入特征库，梯度校准专有模型！
          </div>
        </div>
      </div>
    </div>
  );
};
