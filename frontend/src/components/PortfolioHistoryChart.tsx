import React, { useState, useEffect, useRef } from 'react';

interface PortfolioData {
  success: boolean;
  period: string;
  latest_equity: number;
  base_value: number;
  change_dollar: number;
  change_pct: number;
  asof: string;
  timestamps: number[];
  equity: number[];
  profit_loss_pct?: number[];
  error?: string;
}

const API_BASE = '';

export const PortfolioHistoryChart: React.FC = () => {
  const [period, setPeriod] = useState<string>('1M');
  const [data, setData] = useState<PortfolioData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  const fetchHistory = async (selectedPeriod: string) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/broker/portfolio_history?period=${selectedPeriod}`);
      const json = await res.json();
      if (json.success) {
        setData(json);
      }
    } catch (e) {
      console.error('Failed to fetch portfolio history:', e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHistory(period);
  }, [period]);

  const activeEquity = (hoverIndex !== null && data?.equity?.[hoverIndex] !== undefined)
    ? data.equity[hoverIndex]
    : (data?.latest_equity || 0);

  const baseVal = data?.base_value || (data?.equity?.[0] || 100000);
  const activeChangeDollar = activeEquity - baseVal;
  const activeChangePct = baseVal > 0 ? (activeChangeDollar / baseVal) * 100 : 0;

  const isPositive = activeChangePct >= 0;
  const strokeColor = isPositive ? '#f59e0b' : '#f43f5e';
  const fillColor = isPositive ? 'url(#amberGradient)' : 'url(#roseGradient)';

  const formatCurrency = (val: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(val);
  };

  const formatShortVal = (val: number) => {
    if (val >= 1000000) return `$${(val / 1000000).toFixed(1)}m`;
    if (val >= 1000) return `$${(val / 1000).toFixed(1)}k`;
    return `$${val.toFixed(0)}`;
  };

  const renderChart = () => {
    if (!data || !data.equity || data.equity.length < 2) {
      return null;
    }
    const points = data.equity;
    const minVal = Math.min(...points);
    const maxVal = Math.max(...points);
    const range = (maxVal - minVal) || 1;
    const paddingY = range * 0.1;
    const effectiveMin = Math.max(0, minVal - paddingY);
    const effectiveMax = maxVal + paddingY;
    const effectiveRange = effectiveMax - effectiveMin;

    const width = 800;
    const height = 220;

    const coords = points.map((val, idx) => {
      const x = (idx / (points.length - 1)) * width;
      const y = height - ((val - effectiveMin) / effectiveRange) * height;
      return { x, y, val, ts: data.timestamps[idx] };
    });

    const dPath = coords.reduce((acc, pt, i) => {
      return i === 0 ? `M ${pt.x},${pt.y}` : `${acc} L ${pt.x},${pt.y}`;
    }, '');

    const areaPath = `${dPath} L ${width},${height} L 0,${height} Z`;

    const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
      if (!svgRef.current) return;
      const rect = svgRef.current.getBoundingClientRect();
      const clientX = e.clientX - rect.left;
      const ratio = Math.max(0, Math.min(1, clientX / rect.width));
      const idx = Math.round(ratio * (points.length - 1));
      setHoverIndex(idx);
    };

    const handleMouseLeave = () => setHoverIndex(null);

    const activePt = hoverIndex !== null ? coords[hoverIndex] : null;

    const yTicks = [effectiveMax, (effectiveMax + effectiveMin) / 2, effectiveMin];

    const startDate = data.timestamps[0] ? new Date(data.timestamps[0] * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';
    const endDate = data.timestamps[data.timestamps.length - 1] ? new Date(data.timestamps[data.timestamps.length - 1] * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';
    const midDate = data.timestamps[Math.floor(data.timestamps.length / 2)] ? new Date(data.timestamps[Math.floor(data.timestamps.length / 2)] * 1000).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '';

    return (
      <div style={{ position: 'relative', width: '100%', marginTop: '1.5rem' }}>
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 25, pointerEvents: 'none', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          {yTicks.map((t, idx) => (
            <div key={idx} style={{ display: 'flex', alignItems: 'center' }}>
              <span style={{ fontSize: '0.72rem', color: '#666', width: '50px', transform: 'translateY(-50%)' }}>
                {formatShortVal(t)}
              </span>
              <div style={{ flex: 1, borderTop: '1px dashed rgba(255,255,255,0.06)' }} />
            </div>
          ))}
        </div>

        <svg
          ref={svgRef}
          viewBox={`0 0 ${width} ${height}`}
          style={{ width: '100%', height: '220px', overflow: 'visible', cursor: 'crosshair' }}
          onMouseMove={handleMouseMove}
          onMouseLeave={handleMouseLeave}
        >
          <defs>
            <linearGradient id="amberGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.28" />
              <stop offset="100%" stopColor="#f59e0b" stopOpacity="0.0" />
            </linearGradient>
            <linearGradient id="roseGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#f43f5e" stopOpacity="0.28" />
              <stop offset="100%" stopColor="#f43f5e" stopOpacity="0.0" />
            </linearGradient>
          </defs>

          <path d={areaPath} fill={fillColor} />
          <path d={dPath} fill="none" stroke={strokeColor} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />

          {activePt && (
            <g>
              <line x1={activePt.x} y1="0" x2={activePt.x} y2={height} stroke="rgba(255,255,255,0.3)" strokeWidth="1" strokeDasharray="3,3" />
              <circle cx={activePt.x} cy={activePt.y} r="5" fill={strokeColor} stroke="#fff" strokeWidth="2" />
            </g>
          )}
        </svg>

        <div style={{ display: 'flex', justifyContent: 'space-between', paddingLeft: '50px', marginTop: '8px', fontSize: '0.75rem', color: '#888', fontWeight: 500 }}>
          <span>{startDate}</span>
          <span>{midDate}</span>
          <span>{endDate}</span>
        </div>
      </div>
    );
  };

  return (
    <div className="card" style={{
      background: 'rgba(18, 18, 20, 0.75)',
      backdropFilter: 'blur(16px)',
      border: '1px solid rgba(255, 255, 255, 0.08)',
      borderRadius: '16px',
      padding: '1.75rem',
      marginBottom: '1.75rem',
      boxShadow: '0 8px 32px rgba(0,0,0,0.36)'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ margin: 0, fontSize: '1.25rem', fontWeight: 700, color: '#f3f4f6', letterSpacing: '-0.01em' }}>
          Your portfolio
        </h2>

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <div style={{ display: 'flex', background: 'rgba(255,255,255,0.06)', padding: '3px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.08)' }}>
            {['1D', '1M', '1Y', 'All'].map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                style={{
                  background: period === p ? 'rgba(255,255,255,0.18)' : 'transparent',
                  color: period === p ? '#ffffff' : '#9ca3af',
                  border: 'none',
                  borderRadius: '6px',
                  padding: '4px 12px',
                  fontSize: '0.78rem',
                  fontWeight: 700,
                  cursor: 'pointer',
                  transition: 'all 0.2s ease'
                }}
              >
                {p}
              </button>
            ))}
          </div>

          <button
            onClick={() => fetchHistory(period)}
            style={{
              background: 'rgba(255,255,255,0.06)',
              border: '1px solid rgba(255,255,255,0.08)',
              color: '#9ca3af',
              borderRadius: '8px',
              width: '32px',
              height: '32px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              cursor: 'pointer',
              fontSize: '0.9rem'
            }}
            title="Refresh Portfolio History"
          >
            ↻
          </button>
        </div>
      </div>

      <div style={{ marginTop: '1.2rem' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '12px' }}>
          <span style={{ fontSize: '2.2rem', fontWeight: 800, color: '#ffffff', letterSpacing: '-0.02em', fontFamily: 'Inter, system-ui, -apple-system, sans-serif' }}>
            {formatCurrency(activeEquity)}
          </span>
          <span style={{
            fontSize: '1.15rem',
            fontWeight: 700,
            color: isPositive ? '#10b981' : '#f43f5e',
            display: 'inline-flex',
            alignItems: 'center'
          }}>
            {activeChangePct >= 0 ? '+' : ''}{activeChangePct.toFixed(2)}%
          </span>
        </div>

        <div style={{ fontSize: '0.82rem', color: '#9ca3af', marginTop: '4px', fontWeight: 500 }}>
          {data?.asof || 'Live Broker Stream'}
        </div>
      </div>

      {loading ? (
        <div style={{ height: '220px', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666', fontSize: '0.88rem' }}>
          ⚡ Connecting to Alpaca Portfolio Stream...
        </div>
      ) : (
        renderChart()
      )}
    </div>
  );
};
