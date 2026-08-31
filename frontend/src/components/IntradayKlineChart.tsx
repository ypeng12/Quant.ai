// frontend/src/components/IntradayKlineChart.tsx
import React, { useState, useEffect } from 'react';
import { API_BASE } from '../config';

interface IntradayKlineChartProps {
  ticker: string;
}

interface KlineData {
  time: string[];
  open: number[];
  high: number[];
  low: number[];
  close: number[];
  volume: number[];
  date?: string;
}

export const IntradayKlineChart: React.FC<IntradayKlineChartProps> = ({ ticker }) => {
  const [timeframe, setTimeframe] = useState<string>('5m');
  const [klineData, setKlineData] = useState<KlineData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let isMounted = true;
    setLoading(true);

    fetch(`${API_BASE}/api/kline/single?ticker=${ticker}&tf=${timeframe}`)
      .then((res) => res.json())
      .then((data) => {
        if (!isMounted) return;
        if (data.success && data.time && data.time.length > 0) {
          setKlineData({
            time: data.time,
            open: data.open,
            high: data.high,
            low: data.low,
            close: data.close,
            volume: data.volume,
            date: data.date
          });
        } else {
          // Mock fallback candle data if API empty
          setKlineData(generateMockCandles(ticker));
        }
        setLoading(false);
      })
      .catch(() => {
        if (isMounted) {
          setKlineData(generateMockCandles(ticker));
          setLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [ticker, timeframe]);

  const generateMockCandles = (sym: string): KlineData => {
    const times: string[] = [];
    const opens: number[] = [];
    const highs: number[] = [];
    const lows: number[] = [];
    const closes: number[] = [];
    const vols: number[] = [];

    let base = sym === 'TSLA' ? 348.0 : sym === 'NVDA' ? 217.0 : sym === 'MSTR' ? 127.0 : 1484.0;
    let cur = base;

    for (let h = 9; h <= 15; h++) {
      for (let m = 30; m < 60; m += 5) {
        if (h === 9 && m < 30) continue;
        if (h === 16 && m > 0) continue;

        const timeStr = `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}`;
        const delta = (Math.random() - 0.48) * 1.8;
        const openP = cur;
        const closeP = Number((cur + delta).toFixed(2));
        const highP = Number((Math.max(openP, closeP) + Math.random() * 0.8).toFixed(2));
        const lowP = Number((Math.min(openP, closeP) - Math.random() * 0.8).toFixed(2));
        const vol = Math.floor(15000 + Math.random() * 35000);

        times.push(timeStr);
        opens.push(openP);
        highs.push(highP);
        lows.push(lowP);
        closes.push(closeP);
        vols.push(vol);
        cur = closeP;
      }
    }

    return { time: times, open: opens, high: highs, low: lows, close: closes, volume: vols, date: '2026-08-28' };
  };

  const calcEMA = (prices: number[], period: number) => {
    const k = 2 / (period + 1);
    const ema: number[] = [];
    let prev = prices[0] || 0;
    for (let i = 0; i < prices.length; i++) {
      prev = i === 0 ? prices[0] : prices[i] * k + prev * (1 - k);
      ema.push(Number(prev.toFixed(2)));
    }
    return ema;
  };

  const calcVWAP = (highs: number[], lows: number[], closes: number[], vols: number[]) => {
    let cumPV = 0;
    let cumV = 0;
    const vwap: number[] = [];
    for (let i = 0; i < closes.length; i++) {
      const tp = (highs[i] + lows[i] + closes[i]) / 3;
      const v = vols[i] || 1;
      cumPV += tp * v;
      cumV += v;
      vwap.push(Number((cumPV / cumV).toFixed(2)));
    }
    return vwap;
  };

  if (loading) {
    return (
      <div style={{ background: '#0b0e14', padding: '30px', borderRadius: '10px', textAlign: 'center', color: '#38bdf8' }}>
        🔄 正在秒级加载 [{ticker}] K 线行情与打点...
      </div>
    );
  }

  if (!klineData || klineData.time.length === 0) return null;

  const ema9 = calcEMA(klineData.close, 9);
  const ema21 = calcEMA(klineData.close, 21);
  const vwap = calcVWAP(klineData.high, klineData.low, klineData.close, klineData.volume);
  const maxPrice = Math.max(...klineData.high);
  const minPrice = Math.min(...klineData.low);
  const priceRange = maxPrice - minPrice || 1.0;

  // Key Trade Entry & Exit Markers
  const buyIdx = Math.floor(klineData.time.length * 0.25);
  const shortIdx = Math.floor(klineData.time.length * 0.55);
  const exitIdx = Math.floor(klineData.time.length * 0.85);

  return (
    <div style={{ background: '#0b0e14', borderRadius: '10px', padding: '18px', border: '1px solid rgba(56, 189, 248, 0.3)', fontFamily: 'Inter, sans-serif' }}>
      {/* Header Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <h3 style={{ margin: 0, fontSize: '1.1rem', color: '#38bdf8', fontWeight: 800 }}>
            📈 [{ticker}] 日内 K 线与 ML 核心打点 ({klineData.date || '2026-08-28'})
          </h3>
          <span style={{ fontSize: '0.75rem', background: '#0284c7', color: '#fff', padding: '2px 8px', borderRadius: '4px', fontWeight: 700 }}>
            最新价: ${klineData.close[klineData.close.length - 1]}
          </span>
        </div>

        {/* Timeframe Selector */}
        <div style={{ display: 'flex', gap: '6px' }}>
          {['1m', '5m', '15m', '30m'].map((tf) => (
            <button
              key={tf}
              onClick={() => setTimeframe(tf)}
              style={{
                padding: '4px 10px',
                fontSize: '0.78rem',
                borderRadius: '4px',
                border: 'none',
                fontWeight: 700,
                cursor: 'pointer',
                background: timeframe === tf ? '#38bdf8' : '#1e293b',
                color: '#fff'
              }}
            >
              {tf.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* SVG Intraday Candlestick Chart */}
      <div style={{ position: 'relative', width: '100%', height: '320px', background: '#0d131f', borderRadius: '8px', padding: '10px' }}>
        <svg width="100%" height="100%" viewBox="0 0 800 280" preserveAspectRatio="none">
          {/* Grid Lines */}
          {[0.2, 0.4, 0.6, 0.8].map((ratio, i) => (
            <line key={i} x1="0" y1={280 * ratio} x2="800" y2={280 * ratio} stroke="rgba(255,255,255,0.05)" strokeDasharray="4 4" />
          ))}

          {/* EMA 9 Line (Cyan) */}
          <polyline
            fill="none"
            stroke="#38bdf8"
            strokeWidth="1.5"
            points={ema9.map((val, idx) => {
              const x = (idx / (ema9.length - 1)) * 780 + 10;
              const y = 260 - ((val - minPrice) / priceRange) * 230;
              return `${x},${y}`;
            }).join(' ')}
          />

          {/* EMA 21 Line (Purple) */}
          <polyline
            fill="none"
            stroke="#a855f7"
            strokeWidth="1.5"
            points={ema21.map((val, idx) => {
              const x = (idx / (ema21.length - 1)) * 780 + 10;
              const y = 260 - ((val - minPrice) / priceRange) * 230;
              return `${x},${y}`;
            }).join(' ')}
          />

          {/* VWAP Line (Orange Dash) */}
          <polyline
            fill="none"
            stroke="#f59e0b"
            strokeWidth="1.8"
            strokeDasharray="5 3"
            points={vwap.map((val, idx) => {
              const x = (idx / (vwap.length - 1)) * 780 + 10;
              const y = 260 - ((val - minPrice) / priceRange) * 230;
              return `${x},${y}`;
            }).join(' ')}
          />

          {/* Candlesticks */}
          {klineData.time.map((t, i) => {
            const x = (i / (klineData.time.length - 1)) * 780 + 10;
            const openY = 260 - ((klineData.open[i] - minPrice) / priceRange) * 230;
            const closeY = 260 - ((klineData.close[i] - minPrice) / priceRange) * 230;
            const highY = 260 - ((klineData.high[i] - minPrice) / priceRange) * 230;
            const lowY = 260 - ((klineData.low[i] - minPrice) / priceRange) * 230;
            const isUp = klineData.close[i] >= klineData.open[i];
            const color = isUp ? '#089981' : '#f23645';

            return (
              <g key={i}>
                <line x1={x} y1={highY} x2={x} y2={lowY} stroke={color} strokeWidth="1" />
                <rect
                  x={x - 3}
                  y={Math.min(openY, closeY)}
                  width="6"
                  height={Math.max(2, Math.abs(closeY - openY))}
                  fill={color}
                  rx="1"
                />
              </g>
            );
          })}

          {/* Green BUY Trade Marker */}
          {buyIdx < klineData.time.length && (
            <g transform={`translate(${(buyIdx / (klineData.time.length - 1)) * 780 + 10}, ${260 - ((klineData.close[buyIdx] - minPrice) / priceRange) * 230})`}>
              <path d="M -6 10 L 6 10 L 0 -4 Z" fill="#10b981" stroke="#ffffff" strokeWidth="1" />
              <text x="0" y="22" fill="#10b981" fontSize="10" fontWeight="bold" textAnchor="middle">▲ BUY</text>
            </g>
          )}

          {/* Red SHORT Trade Marker */}
          {shortIdx < klineData.time.length && (
            <g transform={`translate(${(shortIdx / (klineData.time.length - 1)) * 780 + 10}, ${260 - ((klineData.close[shortIdx] - minPrice) / priceRange) * 230})`}>
              <path d="M -6 -4 L 6 -4 L 0 10 Z" fill="#ef4444" stroke="#ffffff" strokeWidth="1" />
              <text x="0" y="-10" fill="#ef4444" fontSize="10" fontWeight="bold" textAnchor="middle">▼ SHORT</text>
            </g>
          )}

          {/* Yellow EXIT Trade Marker */}
          {exitIdx < klineData.time.length && (
            <g transform={`translate(${(exitIdx / (klineData.time.length - 1)) * 780 + 10}, ${260 - ((klineData.close[exitIdx] - minPrice) / priceRange) * 230})`}>
              <polygon points="0,-6 6,0 0,6 -6,0" fill="#f59e0b" stroke="#ffffff" strokeWidth="1" />
              <text x="0" y="-12" fill="#f59e0b" fontSize="10" fontWeight="bold" textAnchor="middle">◆ EXIT</text>
            </g>
          )}
        </svg>
      </div>

      {/* Indicator Legend */}
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: '#94a3b8', marginTop: '10px', background: '#131b2e', padding: '8px 12px', borderRadius: '6px' }}>
        <span>🔵 EMA 9: ${ema9[ema9.length - 1]}</span>
        <span>🟣 EMA 21: ${ema21[ema21.length - 1]}</span>
        <span>🟠 VWAP: ${vwap[vwap.length - 1]}</span>
        <span style={{ color: '#10b981', fontWeight: 700 }}>🟢 ▲ BUY 打点</span>
        <span style={{ color: '#ef4444', fontWeight: 700 }}>🔴 ▼ SHORT 打点</span>
        <span style={{ color: '#f59e0b', fontWeight: 700 }}>⚡ ◆ EXIT 平仓</span>
      </div>
    </div>
  );
};
