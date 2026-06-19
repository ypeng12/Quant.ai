// frontend/src/components/ResearchReportPanel.tsx

import React, { useState, useEffect } from 'react';
import type { StrategyParams } from './StrategySettings';

interface ComponentData {
  type: 'paragraph' | 'heading3' | 'table' | 'code' | 'alert' | 'list';
  content?: string;
  lang?: string;
  alert_type?: string;
  headers?: string[];
  rows?: Record<string, string>[];
  items?: string[];
}

interface SectionData {
  title: string;
  id: string;
  components: ComponentData[];
}

interface ReportResponse {
  success: boolean;
  title: string;
  sections: SectionData[];
  error?: string;
}

interface ResearchReportPanelProps {
  onApplyParams: (config: Partial<StrategyParams>, tab: 'dashboard') => void;
  activeTicker: string;
}

// Checkbox item schema for dynamic storage
interface ChecklistItem {
  id: string;
  label: string;
  category: string;
  checked: boolean;
}

const DEFAULT_CHECKLIST: ChecklistItem[] = [
  { id: '1', label: '离线研究：验证在不同交易周期下参数的最优稳定区，拒绝“孤立最优点”', category: '回测治理', checked: true },
  { id: '2', label: '数据治理：引入复权与原始价分离机制，复权价生成信号，原始价仿真成交', category: '回测治理', checked: true },
  { id: '3', label: '防过拟合：使用 Walk-forward 滚动向前优化及 PBO (概率过拟合) 检测', category: '回测治理', checked: false },
  { id: '4', label: '对账系统：在收盘后对本地仓位账本与券商实际持仓执行自动化对账校验', category: '生产治理', checked: false },
  { id: '5', label: '报警熔断：实现微信/钉钉 API 异常、数据源延迟或账户硬回撤熔断通知', category: '生产治理', checked: false },
  { id: '6', label: '程序化报告：A 股交易前向证券监督管理部门或交易所进行程序化备案登记', category: '合规治理', checked: false },
  { id: '7', label: 'Shadow Live：小资金或空跑两周，检验真实滑点佣金摩擦成本与回测偏差', category: '实盘迁移', checked: false },
];

const formatContent = (text: string): string => {
  return (text || '')
    .replace(/\[cite\|[^\]]*\]/g, '') // Hide citation brackets
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/`(.*?)`/g, '<code>$1</code>');
};

export const ResearchReportPanel: React.FC<ResearchReportPanelProps> = ({ onApplyParams }) => {
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [activeSectionId, setActiveSectionId] = useState<string>('executive_summary');
  
  // Interactive Calculator State
  const [capital, setCapital] = useState<number>(100000);
  const [dailyTarget, setDailyTarget] = useState<number>(500);

  // Sizing Calculator State
  const [accountEquity, setAccountEquity] = useState<number>(100000);
  const [riskPercent, setRiskPercent] = useState<number>(0.5); // 0.5%
  const [atrStopDistance, setAtrStopDistance] = useState<number>(3.5); // $3.5 stop distance

  // A-Share vs US Stock active sub-tab
  const [comparisonMarket, setComparisonMarket] = useState<'A' | 'US'>('US');

  // Candlestick shapes search
  const [candlestickSearch, setCandlestickSearch] = useState<string>('');

  // Checklist state (persisted locally)
  const [checklist, setChecklist] = useState<ChecklistItem[]>(() => {
    const saved = localStorage.getItem('quant_research_checklist');
    return saved ? JSON.parse(saved) : DEFAULT_CHECKLIST;
  });

  useEffect(() => {
    localStorage.setItem('quant_research_checklist', JSON.stringify(checklist));
  }, [checklist]);

  const toggleChecklistItem = (id: string) => {
    setChecklist(prev => prev.map(item => item.id === id ? { ...item, checked: !item.checked } : item));
  };

  useEffect(() => {
    const fetchReport = async () => {
      setLoading(true);
      try {
        const res = await fetch('http://127.0.0.1:8000/api/research_report');
        const json = await res.json();
        if (json.success) {
          setReport(json);
          if (json.sections && json.sections.length > 0) {
            setActiveSectionId(json.sections[0].id);
          }
        } else {
          console.error("Report fetch failed:", json.error);
        }
      } catch (e) {
        console.error("Connection to research API failed:", e);
      } finally {
        setLoading(false);
      }
    };
    fetchReport();
  }, []);

  if (loading) {
    return (
      <div className="loader-container">
        📖 Loading dynamic research report and compilation assets...
      </div>
    );
  }

  if (!report || !report.sections) {
    return (
      <div className="loader-container" style={{ color: 'var(--color-red)' }}>
        ⚠️ Failed to load Deep Research Report. Please ensure the backend server is running and deep-research-report.md is present in the project folder.
      </div>
    );
  }

  // Calculate annual return needed based on inputs
  // Required Annual Return = (Daily Target * 252 trading days / Capital) * 100
  const annualReturnRequired = (dailyTarget * 252 / capital) * 100;
  
  let feasibilityLabel = "";
  let feasibilityClass = "";
  let feasibilityDesc = "";

  if (annualReturnRequired > 100) {
    feasibilityLabel = "🔴 极高风险 / 几乎不可能";
    feasibilityClass = "danger";
    feasibilityDesc = "对于日线级别股票交易，超过 100% 的年化净收益率在统计上是极其罕见且不可持续的。这需要你使用极高杠杆或承担毁灭性的回撤风险，极易导致爆仓。建议增加初始本金或降低每日收益目标。";
  } else if (annualReturnRequired >= 50) {
    feasibilityLabel = "🟠 高度激进 / 极具挑战";
    feasibilityClass = "warning";
    feasibilityDesc = "50% - 100% 的年化净收益率属于专业量化基金的顶尖水平或高杠杆趋势行情下的特殊表现。需要极高胜率、极佳的滑点控制和高度一致的系统执行，伴随的系统性回撤风险也相当高。";
  } else if (annualReturnRequired >= 20) {
    feasibilityLabel = "💛 中度合理 / 可以争取";
    feasibilityClass = "moderate";
    feasibilityDesc = "20% - 50% 年化复合收益率。在多策略并行、严格资金管理、以及牛市或高动量市场环境下，是一个可以通过精细化系统交易去争取的理性目标。";
  } else {
    feasibilityLabel = "💚 稳健安全 / 可行性高";
    feasibilityClass = "success";
    feasibilityDesc = "低于 20% 年化回报。最符合低频日线执行、资产均衡配置与稳健风控的现实路径。系统对单次执行偏差与交易摩擦的敏感度较低，抗风险能力最强。";
  }

  // Sizing Calculator Formula: Qty = (Equity * RiskPercent / 100) / StopDistance
  const riskAmountDollar = accountEquity * (riskPercent / 100);
  const sharesToBuy = Math.floor(riskAmountDollar / (atrStopDistance || 0.01));
  const totalPositionValue = sharesToBuy * 150; // Assume stock price is $150 for illustration

  // SVGs for K-Lines
  const renderKLineSVG = (patternName: string) => {
    const name = patternName.toLowerCase();
    
    // SVG standard settings
    const width = 60;
    const height = 90;
    
    if (name.includes('hammer') || name.includes('锤子')) {
      return (
        <svg width={width} height={height} viewBox="0 0 60 90">
          <line x1="30" y1="10" x2="30" y2="80" stroke="var(--color-green)" strokeWidth="2" />
          <rect x="20" y="20" width="20" height="15" fill="var(--color-green)" rx="2" />
        </svg>
      );
    }
    if (name.includes('star') || name.includes('流星') || name.includes('黄昏')) {
      return (
        <svg width={width} height={height} viewBox="0 0 60 90">
          <line x1="30" y1="10" x2="30" y2="80" stroke="var(--color-red)" strokeWidth="2" />
          <rect x="20" y="55" width="20" height="15" fill="var(--color-red)" rx="2" />
        </svg>
      );
    }
    if (name.includes('doji') || name.includes('十字星')) {
      return (
        <svg width={width} height={height} viewBox="0 0 60 90">
          <line x1="30" y1="15" x2="30" y2="75" stroke="#ffffff" strokeWidth="2" />
          <line x1="15" y1="45" x2="45" y2="45" stroke="#ffffff" strokeWidth="3" />
        </svg>
      );
    }
    if (name.includes('engulfing') || name.includes('吞没')) {
      const isBull = name.includes('bullish') || name.includes('看涨');
      return (
        <svg width={width} height={height} viewBox="0 0 60 90">
          {/* Left candle (small) */}
          <line x1="20" y1="35" x2="20" y2="65" stroke={isBull ? 'var(--color-red)' : 'var(--color-green)'} strokeWidth="2" />
          <rect x="12" y="42" width="16" height="16" fill={isBull ? 'var(--color-red)' : 'var(--color-green)'} />
          
          {/* Right candle (big engulfing) */}
          <line x1="42" y1="15" x2="42" y2="80" stroke={isBull ? 'var(--color-green)' : 'var(--color-red)'} strokeWidth="2" />
          <rect x="34" y="25" width="16" height="42" fill={isBull ? 'var(--color-green)' : 'var(--color-red)'} />
        </svg>
      );
    }
    if (name.includes('marubozu') || name.includes('光头')) {
      const isBull = name.includes('bull') || name.includes('长阳') || name.includes('红');
      return (
        <svg width={width} height={height} viewBox="0 0 60 90">
          <rect x="20" y="15" width="20" height="60" fill={isBull ? 'var(--color-green)' : 'var(--color-red)'} />
        </svg>
      );
    }
    // Default Spinning Top style
    return (
      <svg width={width} height={height} viewBox="0 0 60 90">
        <line x1="30" y1="15" x2="30" y2="75" stroke="var(--color-text-secondary)" strokeWidth="2" />
        <rect x="22" y="35" width="16" height="20" fill="var(--color-text-secondary)" rx="1" />
      </svg>
    );
  };

  // Specific Candlestick configurations that we can map parameters to
  const candlestickData: Array<{
    name: string;
    type: string;
    formula: string;
    desc: string;
    strategy: Partial<StrategyParams>;
  }> = [
    { name: "长阳线 / 大阳线 (Big Bullish)", type: "bullish", formula: "bull and body_ratio >= 0.6 and upper_ratio <= 0.3 and lower_ratio <= 0.3", desc: "买方全天绝对主导，代表多头攻击动能充沛，后市看涨概率大。", strategy: { strategy_mode: "patterns", trailing_stop_atr_mult: 2.0 } },
    { name: "长阴线 / 大阴线 (Big Bearish)", type: "bearish", formula: "bear and body_ratio >= 0.6 and upper_ratio <= 0.3 and lower_ratio <= 0.3", desc: "空方全天绝对掌控，恐慌情绪蔓延，通常需要离场防御。", strategy: { strategy_mode: "dynamic" } },
    { name: "十字星 (Doji)", type: "neutral", formula: "body_ratio <= 0.1", desc: "多空平衡，波动率收缩。处于长期趋势末端常代表变盘，处于趋势中途代表调整中继。", strategy: { strategy_mode: "consensus" } },
    { name: "锤头线 (Hammer)", type: "bullish", formula: "lower_ratio >= 2.0 and upper_ratio <= 0.5 and body_ratio <= 0.35 and trend_down_ctx", desc: "底部强力吸筹，价格探底回升。在均线支撑位或超卖区具有极高可靠性。", strategy: { strategy_mode: "patterns", trailing_stop_atr_mult: 1.5 } },
    { name: "射击之星 (Shooting Star)", type: "bearish", formula: "upper_ratio >= 2.0 and lower_ratio <= 0.5 and body_ratio <= 0.35 and trend_up_ctx", desc: "上方抛压沉重，多头冲高回落，是经典的高位见顶抛售信号。", strategy: { strategy_mode: "patterns", profit_target_pct: 0.02 } },
    { name: "看涨吞没 (Bullish Engulfing)", type: "bullish", formula: "prev.close < prev.open and curr.close > curr.open and curr.open <= prev.close and curr.close >= prev.open", desc: "后一根阳线实体完全覆盖前一根阴线实体，是多头强力反攻的底部信号。", strategy: { strategy_mode: "patterns", trailing_stop_atr_mult: 2.5 } },
    { name: "看跌吞没 (Bearish Engulfing)", type: "bearish", formula: "prev.close > prev.open and curr.close < curr.open and curr.open >= prev.close and curr.close <= prev.open", desc: "后一根阴线实体覆盖前一阳线，说明多头撤退，空头全盘接管。", strategy: { strategy_mode: "patterns" } }
  ];

  return (
    <div className="research-panel">
      {/* 侧边导航栏 & 头部标题 */}
      <div className="research-layout">
        
        {/* 左侧文档树目录 */}
        <aside className="research-toc">
          <div className="toc-title">📚 报告目录</div>
          <div className="toc-list">
            {report.sections.map((sec) => (
              <button
                key={sec.id}
                className={`toc-item ${activeSectionId === sec.id ? 'active' : ''}`}
                onClick={() => {
                  setActiveSectionId(sec.id);
                  const el = document.getElementById(`doc-sec-${sec.id}`);
                  el?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                }}
              >
                {sec.title}
              </button>
            ))}
          </div>
          
          <div className="toc-apply-widget">
            <div className="toc-widget-title">⚙️ 策略一键绑定</div>
            <p style={{ fontSize: '0.75rem', margin: '4px 0 10px 0', color: 'var(--color-text-secondary)' }}>
              直接把报告中的最优起始参数参数加载到当前的仿真测试面板：
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <button
                className="btn-apply-preset dynamic"
                onClick={() => onApplyParams({
                  strategy_mode: 'dynamic',
                  trailing_stop_mode: 'atr',
                  trailing_stop_atr_mult: 2.0,
                  stop_loss_pct: 0.015,
                  profit_target_pct: 0.030,
                  risk_per_trade_pct: 0.005,
                  position_sizing_mode: 'atr'
                }, 'dashboard')}
              >
                🚦 加载 动态路由系统
              </button>
              <button
                className="btn-apply-preset trend"
                onClick={() => onApplyParams({
                  strategy_mode: 'breakout',
                  trailing_stop_mode: 'atr',
                  trailing_stop_atr_mult: 2.5,
                  stop_loss_pct: 0.02,
                  profit_target_pct: 0.05,
                  position_sizing_mode: 'flat'
                }, 'dashboard')}
              >
                📈 加载 唐奇安突破系统
              </button>
              <button
                className="btn-apply-preset reversion"
                onClick={() => onApplyParams({
                  strategy_mode: 'patterns',
                  trailing_stop_mode: 'flat',
                  stop_loss_pct: 0.01,
                  profit_target_pct: 0.015,
                  rsi_threshold_buy: 30
                }, 'dashboard')}
              >
                📉 加载 K线形态反转
              </button>
            </div>
          </div>
        </aside>

        {/* 右侧交互式文档主体 */}
        <main className="research-doc-body">
          
          {report.sections.map((sec) => (
            <section
              key={sec.id}
              id={`doc-sec-${sec.id}`}
              className={`doc-section-card ${activeSectionId === sec.id ? 'highlight' : ''}`}
            >
              <h2 className="doc-section-title">{sec.title}</h2>
              
              {/* 1. 执行摘要：挂载“资金-收益可行性计算器” */}
              {sec.id === 'executive_summary' && (
                <div className="interactive-widget-wrapper card" style={{ marginTop: '1.25rem', marginBottom: '1.5rem', borderColor: 'var(--color-green)' }}>
                  <h3 className="widget-header">📊 交易目标与本金可行性评估工具</h3>
                  <p style={{ fontSize: '0.82rem', color: 'var(--color-text-secondary)', marginBottom: '1rem' }}>
                    你的目标是<b>长期平均每天净赚 500 美元</b>。根据市场统计学，年化净收益率（按 252 个交易日计）与所需本金存在以下动态关系。移动滑块查看您的方案可行性。
                  </p>
                  
                  <div className="calculator-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
                    <div className="inputs-column">
                      <div className="calc-input-group">
                        <label>初始本金 (USD): <strong>${capital.toLocaleString()}</strong></label>
                        <input
                          type="range"
                          min="10000"
                          max="1000000"
                          step="10000"
                          value={capital}
                          onChange={(e) => setCapital(Number(e.target.value))}
                        />
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#555' }}>
                          <span>$10k</span>
                          <span>$250k</span>
                          <span>$500k</span>
                          <span>$1M</span>
                        </div>
                      </div>
                      
                      <div className="calc-input-group" style={{ marginTop: '1rem' }}>
                        <label>每日平均净目标 (USD): <strong>${dailyTarget}</strong></label>
                        <input
                          type="range"
                          min="50"
                          max="2000"
                          step="50"
                          value={dailyTarget}
                          onChange={(e) => setDailyTarget(Number(e.target.value))}
                        />
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#555' }}>
                          <span>$50</span>
                          <span>$500</span>
                          <span>$1000</span>
                          <span>$2000</span>
                        </div>
                      </div>
                    </div>
                    
                    <div className="outputs-column" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', background: '#111', padding: '1rem', borderRadius: '8px', border: '1px solid #222' }}>
                      <div className="calc-stat-box">
                        <span className="calc-stat-label">目标年增长率 (Required Return)</span>
                        <div className="calc-stat-value" style={{ color: annualReturnRequired > 50 ? 'var(--color-red)' : 'var(--color-green)', fontSize: '2rem', fontWeight: 800 }}>
                          {annualReturnRequired.toFixed(1)}%
                        </div>
                      </div>
                      
                      <div className="calc-stat-box" style={{ marginTop: '10px' }}>
                        <span className="calc-stat-label">系统评级 (Feasibility Rating)</span>
                        <div className={`feasibility-badge ${feasibilityClass}`} style={{ fontWeight: 700, margin: '6px 0', fontSize: '0.95rem' }}>
                          {feasibilityLabel}
                        </div>
                        <p style={{ fontSize: '0.78rem', color: 'var(--color-text-secondary)', margin: '4px 0 0 0', lineHeight: 1.4 }}>
                          {feasibilityDesc}
                        </p>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* 2. 关键目标与约束：A股与美股规则的对比切换卡片 */}
              {sec.id === 'key_goals___constraints' && (
                <div className="interactive-widget-wrapper card" style={{ marginTop: '1.25rem', marginBottom: '1.5rem' }}>
                  <h3 className="widget-header">🇺🇸 / 🇨🇳 市场环境与规则适配器</h3>
                  <p style={{ fontSize: '0.82rem', color: 'var(--color-text-secondary)', marginBottom: '1rem' }}>
                    代码必须通过策略底层适配器屏蔽市场交易差异。切换标签对比主要规则：
                  </p>
                  
                  <div className="tab-buttons" style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
                    <button
                      className={`tab-btn ${comparisonMarket === 'US' ? 'active' : ''}`}
                      onClick={() => setComparisonMarket('US')}
                    >
                      🇺🇸 美股规则 (US Equities)
                    </button>
                    <button
                      className={`tab-btn ${comparisonMarket === 'A' ? 'active' : ''}`}
                      onClick={() => setComparisonMarket('A')}
                    >
                      🇨🇳 A股规则 (China A-Shares)
                    </button>
                  </div>
                  
                  <div className="market-details-card" style={{ background: '#111', padding: '1.25rem', borderRadius: '8px', border: '1px solid #222' }}>
                    {comparisonMarket === 'US' ? (
                      <div>
                        <div className="market-detail-row"><strong>交易时间：</strong>9:30 - 16:00 ET (盘前 4:00-9:30, 盘后 16:00-20:00)</div>
                        <div className="market-detail-row"><strong>交收规则：</strong>支持 T+0 日内回转交易（不再受旧 PDT 限制，采用 FINRA Rule 4210 日内保证金制）。</div>
                        <div className="market-detail-row"><strong>做空规则：</strong>允许直接借券做空，可融券票池庞大。</div>
                        <div className="market-detail-row"><strong>杠杆机制：</strong>Reg T 初始 50% 保证金率，且盘中日内保证金实时核算。</div>
                        <div className="market-detail-row"><strong>监管要求：</strong>零售账户低门槛，交易系统需遵守券商 API 调用速率限制。</div>
                      </div>
                    ) : (
                      <div>
                        <div className="market-detail-row"><strong>交易时间：</strong>9:30-11:30, 13:00-15:00 CST (有精确开收盘集合竞价段)。</div>
                        <div className="market-detail-row"><strong>交收规则：</strong>实行普通股票 <b>T+1</b> 机制，买入当日不可卖出，需等次日交收。</div>
                        <div className="market-detail-row"><strong>做空规则：</strong>普通散户难以融券，做空通常需要股指期货对冲或融券白名单。</div>
                        <div className="market-detail-row"><strong>杠杆机制：</strong>主要依赖券商融资融券，杠杆率受严控。</div>
                        <div className="market-detail-row"><strong>程序化报告：</strong>深沪交易所针对个人及机构程序化交易要求事先备案报告（包括软件标识、最高申报速度等）。</div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* 3. K线与技术指标：挂载“常见K线形态库”与 SVG 可视化 */}
              {sec.id === 'kline_patterns___indicators' && (
                <div className="interactive-widget-wrapper card" style={{ marginTop: '1.25rem', marginBottom: '1.5rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px', marginBottom: '12px' }}>
                    <h3 className="widget-header" style={{ margin: 0 }}>🕯️ 常见日线 K 线形态智能识别库</h3>
                    <input
                      type="text"
                      className="search-input"
                      placeholder="搜索形态, 如 Hammer..."
                      value={candlestickSearch}
                      onChange={(e) => setCandlestickSearch(e.target.value)}
                      style={{
                        background: '#111',
                        border: '1px solid var(--color-border)',
                        borderRadius: '6px',
                        padding: '6px 12px',
                        color: '#fff',
                        fontSize: '0.8rem',
                        minWidth: '200px'
                      }}
                    />
                  </div>
                  
                  <div className="candlestick-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: '1rem' }}>
                    {candlestickData
                      .filter(item => item.name.toLowerCase().includes(candlestickSearch.toLowerCase()) || item.desc.includes(candlestickSearch))
                      .map((item, idx) => (
                        <div key={idx} className={`candlestick-card border-${item.type}`} style={{ display: 'flex', background: '#111', border: '1px solid #222', borderRadius: '8px', padding: '12px', gap: '12px', position: 'relative' }}>
                          <div className="candlestick-visual" style={{ background: '#000', borderRadius: '4px', padding: '4px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            {renderKLineSVG(item.name)}
                          </div>
                          <div className="candlestick-info" style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                            <div>
                              <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#fff' }}>{item.name}</div>
                              <div style={{ fontSize: '0.7rem', color: 'var(--color-text-secondary)', margin: '4px 0', lineHeight: 1.3 }}>{item.desc}</div>
                              <code style={{ fontSize: '0.62rem', background: '#000', padding: '2px 4px', borderRadius: '3px', color: '#00c805', fontFamily: 'monospace', wordBreak: 'break-all', display: 'block', marginTop: '4px' }}>
                                {item.formula}
                              </code>
                            </div>
                            
                            <button
                              className="btn-apply-mini"
                              onClick={() => onApplyParams(item.strategy, 'dashboard')}
                              style={{
                                border: '1px solid rgba(0,200,5,0.3)',
                                background: 'rgba(0,200,5,0.06)',
                                color: 'var(--color-green)',
                                fontSize: '0.65rem',
                                padding: '3px 6px',
                                borderRadius: '4px',
                                cursor: 'pointer',
                                marginTop: '8px',
                                width: 'fit-content'
                              }}
                            >
                              ⚡ 应用到形态回测
                            </button>
                          </div>
                          
                          <span className={`badge-type ${item.type}`} style={{ position: 'absolute', top: '8px', right: '8px', fontSize: '0.6rem', padding: '2px 5px', borderRadius: '3px' }}>
                            {item.type === 'bullish' ? '看涨' : item.type === 'bearish' ? '看跌' : '中性'}
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* 4. 量化策略清单：挂载“Regime Router 架构流图” */}
              {sec.id === 'quantitative_strategy_checklist' && (
                <div className="interactive-widget-wrapper card" style={{ marginTop: '1.25rem', marginBottom: '1.5rem' }}>
                  <h3 className="widget-header">🚦 Regime Router 市场状态路由引擎架构</h3>
                  <p style={{ fontSize: '0.82rem', color: 'var(--color-text-secondary)', marginBottom: '1rem' }}>
                    本系统并不是盲目执行单一策略，而是先通过 Regime Classifier 进行环境识别，再将决策权路由给子模块：
                  </p>
                  
                  <div style={{ display: 'flex', justifyContent: 'center', background: '#111', padding: '1.5rem', borderRadius: '8px', border: '1px solid #222', marginBottom: '12px' }}>
                    <svg width="600" height="260" viewBox="0 0 600 260">
                      {/* Inputs */}
                      <rect x="10" y="100" width="100" height="50" fill="#2c2c2e" rx="6" stroke="#444" strokeWidth="1.5" />
                      <text x="60" y="130" fill="#fff" fontSize="11" fontWeight="bold" textAnchor="middle">行情 OHLCV 输入</text>
                      
                      {/* Arrow 1 */}
                      <path d="M 110 125 L 150 125" stroke="#888" strokeWidth="1.5" markerEnd="url(#arrow)" />
                      
                      {/* Classifier */}
                      <rect x="150" y="70" width="120" height="110" fill="#1e1e1e" rx="8" stroke="var(--color-green)" strokeWidth="2" />
                      <text x="210" y="100" fill="#fff" fontSize="11" fontWeight="bold" textAnchor="middle">Regime Classifier</text>
                      <text x="210" y="125" fill="#888" fontSize="9" textAnchor="middle">- ADX 趋势强度</text>
                      <text x="210" y="140" fill="#888" fontSize="9" textAnchor="middle">- 均线多空斜率</text>
                      <text x="210" y="155" fill="#888" fontSize="9" textAnchor="middle">- ATR 波动分位数</text>
                      
                      {/* Split Arrows */}
                      <path d="M 270 100 L 330 50" stroke="#888" strokeWidth="1.5" markerEnd="url(#arrow)" />
                      <path d="M 270 125 L 330 125" stroke="#888" strokeWidth="1.5" markerEnd="url(#arrow)" />
                      <path d="M 270 150 L 330 200" stroke="#888" strokeWidth="1.5" markerEnd="url(#arrow)" />
                      
                      {/* Branch 1 */}
                      <rect x="330" y="20" width="130" height="50" fill="rgba(0, 200, 5, 0.15)" rx="6" stroke="var(--color-green)" strokeWidth="1" />
                      <text x="395" y="45" fill="var(--color-green)" fontSize="11" fontWeight="bold" textAnchor="middle">Trend Up (趋势做多)</text>
                      <text x="395" y="60" fill="#aaa" fontSize="8" textAnchor="middle">Donchian 突破 / EMA 金叉</text>
                      
                      {/* Branch 2 */}
                      <rect x="330" y="100" width="130" height="50" fill="rgba(175, 82, 222, 0.15)" rx="6" stroke="#af52de" strokeWidth="1" />
                      <text x="395" y="125" fill="#af52de" fontSize="11" fontWeight="bold" textAnchor="middle">Range Bound (均值回归)</text>
                      <text x="395" y="140" fill="#aaa" fontSize="8" textAnchor="middle">RSI 超卖 / 布林下轨支撑</text>
                      
                      {/* Branch 3 */}
                      <rect x="330" y="180" width="130" height="50" fill="rgba(255, 59, 48, 0.15)" rx="6" stroke="var(--color-red)" strokeWidth="1" />
                      <text x="395" y="205" fill="var(--color-red)" fontSize="11" fontWeight="bold" textAnchor="middle">Trend Down / High Vol</text>
                      <text x="395" y="220" fill="#aaa" fontSize="8" textAnchor="middle">强制风控平仓 / 保持空仓</text>
                      
                      {/* Merge Arrows */}
                      <path d="M 460 45 L 510 100" stroke="#888" strokeWidth="1.5" markerEnd="url(#arrow)" />
                      <path d="M 460 125 L 510 125" stroke="#888" strokeWidth="1.5" markerEnd="url(#arrow)" />
                      <path d="M 460 205 L 510 150" stroke="#888" strokeWidth="1.5" markerEnd="url(#arrow)" />
                      
                      {/* Risk Gate */}
                      <rect x="510" y="100" width="80" height="50" fill="#2c2c2e" rx="6" stroke="#444" strokeWidth="1.5" />
                      <text x="550" y="125" fill="#fff" fontSize="11" fontWeight="bold" textAnchor="middle">下单风控层</text>
                      <text x="550" y="140" fill="var(--color-green)" fontSize="9" textAnchor="middle">次日订单计划</text>
                      
                      {/* Marker Definitions */}
                      <defs>
                        <marker id="arrow" viewBox="0 0 10 10" refX="6" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
                          <path d="M 0 2 L 10 5 L 0 8 z" fill="#888" />
                        </marker>
                      </defs>
                    </svg>
                  </div>
                </div>
              )}

              {/* 5. 风控与资金管理：挂载“单笔仓位风险控制计算器” */}
              {sec.id === 'risk_control___capital_management' && (
                <div className="interactive-widget-wrapper card" style={{ marginTop: '1.25rem', marginBottom: '1.5rem' }}>
                  <h3 className="widget-header">🛡️ 单笔交易头寸风险计算器 (ATR-Based Sizing)</h3>
                  <p style={{ fontSize: '0.82rem', color: 'var(--color-text-secondary)', marginBottom: '1rem' }}>
                    不要主观觉得该买多少股，应当让系统根据<b>最大风险预算</b>和<b>止损距离</b>来反推头寸规模：
                  </p>
                  
                  <div className="calculator-grid" style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '1.5rem' }}>
                    <div className="inputs-column" style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      <div className="calc-input-group">
                        <label>账户净资产 (Equity): <strong>${accountEquity.toLocaleString()}</strong></label>
                        <input
                          type="range"
                          min="10000"
                          max="500000"
                          step="5000"
                          value={accountEquity}
                          onChange={(e) => setAccountEquity(Number(e.target.value))}
                        />
                      </div>
                      
                      <div className="calc-input-group">
                        <label>单笔最大亏损预算 (Risk %): <strong>{riskPercent}%</strong></label>
                        <input
                          type="range"
                          min="0.1"
                          max="2.0"
                          step="0.05"
                          value={riskPercent}
                          onChange={(e) => setRiskPercent(Number(e.target.value))}
                        />
                      </div>
                      
                      <div className="calc-input-group">
                        <label>止损距离 (如 2*ATR, USD): <strong>${atrStopDistance}</strong></label>
                        <input
                          type="range"
                          min="0.5"
                          max="15"
                          step="0.1"
                          value={atrStopDistance}
                          onChange={(e) => setAtrStopDistance(Number(e.target.value))}
                        />
                      </div>
                    </div>
                    
                    <div className="outputs-column" style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center', background: '#111', padding: '1rem', borderRadius: '8px', border: '1px solid #222' }}>
                      <div className="calc-stat-box" style={{ borderBottom: '1px solid #222', paddingBottom: '10px' }}>
                        <span className="calc-stat-label">单笔最大可承受亏损</span>
                        <div style={{ color: 'var(--color-red)', fontSize: '1.4rem', fontWeight: 800 }}>
                          ${riskAmountDollar.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </div>
                      </div>
                      
                      <div className="calc-stat-box" style={{ marginTop: '10px' }}>
                        <span className="calc-stat-label">建议买入数量 (Position Size)</span>
                        <div style={{ color: 'var(--color-green)', fontSize: '1.8rem', fontWeight: 800 }}>
                          {sharesToBuy.toLocaleString()} 股
                        </div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--color-text-secondary)', marginTop: '4px' }}>
                          (以每股 $150 估算，占用保证金约 ${totalPositionValue.toLocaleString()}，敞口占比 {(totalPositionValue / accountEquity * 100).toFixed(1)}%)
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* 6. 回测与参数优化：Walk-Forward 优化流向图 */}
              {sec.id === 'backtesting___parameter_optimization' && (
                <div className="interactive-widget-wrapper card" style={{ marginTop: '1.25rem', marginBottom: '1.5rem' }}>
                  <h3 className="widget-header">🔄 Walk-Forward 滚动向前优化流程线</h3>
                  <p style={{ fontSize: '0.82rem', color: 'var(--color-text-secondary)', marginBottom: '1rem' }}>
                    为了防止参数过拟合于历史噪音，我们必须进行样本内外的滑动窗滚动测试：
                  </p>
                  
                  <div style={{ display: 'flex', justifyContent: 'center', background: '#111', padding: '1.5rem', borderRadius: '8px', border: '1px solid #222' }}>
                    <svg width="600" height="180" viewBox="0 0 600 180">
                      {/* Time bar */}
                      <line x1="20" y1="30" x2="580" y2="30" stroke="#444" strokeWidth="4" strokeLinecap="round" />
                      <text x="20" y="20" fill="#555" fontSize="9">历史起点</text>
                      <text x="580" y="20" fill="#555" fontSize="9" textAnchor="end">未来/实盘</text>
                      
                      {/* Window 1 */}
                      <rect x="50" y="50" width="180" height="30" fill="rgba(142, 142, 147, 0.2)" stroke="#8e8e93" strokeWidth="1" rx="4" />
                      <text x="140" y="68" fill="#fff" fontSize="10" textAnchor="middle">训练集 (Train) 1</text>
                      
                      <rect x="230" y="50" width="90" height="30" fill="rgba(0, 200, 5, 0.2)" stroke="var(--color-green)" strokeWidth="1" rx="4" />
                      <text x="275" y="68" fill="var(--color-green)" fontSize="10" textAnchor="middle">测试集 (Test) 1</text>
                      
                      {/* Window 2 (shifted) */}
                      <rect x="140" y="90" width="180" height="30" fill="rgba(142, 142, 147, 0.2)" stroke="#8e8e93" strokeWidth="1" rx="4" />
                      <text x="230" y="108" fill="#fff" fontSize="10" textAnchor="middle">训练集 (Train) 2</text>
                      
                      <rect x="320" y="90" width="90" height="30" fill="rgba(0, 200, 5, 0.2)" stroke="var(--color-green)" strokeWidth="1" rx="4" />
                      <text x="365" y="108" fill="var(--color-green)" fontSize="10" textAnchor="middle">测试集 (Test) 2</text>
                      
                      {/* Window 3 (shifted) */}
                      <rect x="230" y="130" width="180" height="30" fill="rgba(142, 142, 147, 0.2)" stroke="#8e8e93" strokeWidth="1" rx="4" />
                      <text x="320" y="148" fill="#fff" fontSize="10" textAnchor="middle">训练集 (Train) 3</text>
                      
                      <rect x="410" y="130" width="90" height="30" fill="rgba(0, 200, 5, 0.2)" stroke="var(--color-green)" strokeWidth="1" rx="4" />
                      <text x="455" y="148" fill="var(--color-green)" fontSize="10" textAnchor="middle">测试集 (Test) 3</text>
                    </svg>
                  </div>
                </div>
              )}

              {/* 7. 实盘部署与代码清单：挂载源码链接 */}
              {sec.id === 'production_deployment___code_checklist' && (
                <div className="interactive-widget-wrapper card" style={{ marginTop: '1.25rem', marginBottom: '1.5rem' }}>
                  <h3 className="widget-header">💻 量化策略引擎代码模块导航</h3>
                  <p style={{ fontSize: '0.82rem', color: 'var(--color-text-secondary)', marginBottom: '1rem' }}>
                    Quant.ai 项目的后端量化逻辑采用模块化设计。点击直接阅读相关代码：
                  </p>
                  
                  <div className="code-links-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                    <a href="file:///c:/Users/pengy/OneDrive/Desktop/Quont/backend/app/config.py" className="code-link-item">
                      <span className="file-icon">🐍</span>
                      <div>
                        <strong>config.py</strong>
                        <span>风险限额与基础下单配置参数</span>
                      </div>
                    </a>
                    
                    <a href="file:///c:/Users/pengy/OneDrive/Desktop/Quont/backend/app/data_manager.py" className="code-link-item">
                      <span className="file-icon">🐍</span>
                      <div>
                        <strong>data_manager.py</strong>
                        <span>日线及高频数据拉取与指标计算</span>
                      </div>
                    </a>
                    
                    <a href="file:///c:/Users/pengy/OneDrive/Desktop/Quont/backend/app/patterns.py" className="code-link-item">
                      <span className="file-icon">🐍</span>
                      <div>
                        <strong>patterns.py</strong>
                        <span>K线特征提取与22种技术形态检测</span>
                      </div>
                    </a>
                    
                    <a href="file:///c:/Users/pengy/OneDrive/Desktop/Quont/backend/app/strategy.py" className="code-link-item">
                      <span className="file-icon">🐍</span>
                      <div>
                        <strong>strategy.py</strong>
                        <span>状态识别与动态路由交易逻辑引擎</span>
                      </div>
                    </a>
                    
                    <a href="file:///c:/Users/pengy/OneDrive/Desktop/Quont/backend/app/simulator.py" className="code-link-item">
                      <span className="file-icon">🐍</span>
                      <div>
                        <strong>simulator.py</strong>
                        <span>支持佣金/滑点/日内风控的仿真回测器</span>
                      </div>
                    </a>
                    
                    <a href="file:///c:/Users/pengy/OneDrive/Desktop/Quont/backend/app/risk_analyst.py" className="code-link-item">
                      <span className="file-icon">🐍</span>
                      <div>
                        <strong>risk_analyst.py</strong>
                        <span>多维度回撤及资金成本压力检测报告生成</span>
                      </div>
                    </a>
                  </div>
                </div>
              )}

              {/* 8. 参考来源与合规风险提示：挂载 checklist 跟踪 */}
              {sec.id === 'references___compliance_risk_alert' && (
                <div className="interactive-widget-wrapper card" style={{ marginTop: '1.25rem', marginBottom: '1.5rem', borderColor: 'var(--color-red)' }}>
                  <h3 className="widget-header">📋 量化系统“回测至实盘”迁移合规与风控自查表</h3>
                  <p style={{ fontSize: '0.82rem', color: 'var(--color-text-secondary)', marginBottom: '12px' }}>
                    在系统准备进入模拟盘或实盘运行前，您需要手动验证以下各维度的完备性。勾选可保存自查进度：
                  </p>
                  
                  <div className="checklist-container" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {checklist.map(item => (
                      <label key={item.id} className="checklist-item-row" style={{ display: 'flex', alignItems: 'flex-start', gap: '10px', background: '#111', padding: '10px 14px', borderRadius: '6px', cursor: 'pointer', border: '1px solid #222' }}>
                        <input
                          type="checkbox"
                          checked={item.checked}
                          onChange={() => toggleChecklistItem(item.id)}
                          style={{ marginTop: '3px', cursor: 'pointer' }}
                        />
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: '0.82rem', fontWeight: 600, color: item.checked ? 'var(--color-text-secondary)' : '#fff', textDecoration: item.checked ? 'line-through' : 'none' }}>
                            {item.label}
                          </div>
                          <span style={{ fontSize: '0.62rem', background: '#2c2c2e', color: 'var(--color-text-secondary)', padding: '1px 5px', borderRadius: '3px', marginTop: '4px', display: 'inline-block' }}>
                            {item.category}
                          </span>
                        </div>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              {/* 渲染 Markdown 的普通组件 */}
              {sec.components.map((comp, cidx) => {
                if (comp.type === 'paragraph') {
                  return (
                    <p key={cidx} className="doc-paragraph" dangerouslySetInnerHTML={{
                      __html: formatContent(comp.content || '')
                    }} />
                  );
                }
                
                if (comp.type === 'heading3') {
                  return <h3 key={cidx} className="doc-heading3">{comp.content}</h3>;
                }
                
                if (comp.type === 'table' && comp.headers && comp.rows) {
                  // If it's a table, let's render it as a premium HTML table
                  return (
                    <div key={cidx} className="doc-table-wrapper" style={{ overflowX: 'auto', margin: '1rem 0' }}>
                      <table className="ledger-table" style={{ width: '100%' }}>
                        <thead>
                          <tr>
                            {comp.headers.map((h, hidx) => (
                              <th key={hidx}>{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {comp.rows.map((row, ridx) => (
                            <tr key={ridx}>
                              {comp.headers!.map((h, colidx) => (
                                <td key={colidx} style={{ fontSize: '0.82rem' }}>{row[h]}</td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  );
                }
                
                if (comp.type === 'code') {
                  return (
                    <div key={cidx} className="doc-code-wrapper" style={{ position: 'relative', margin: '1rem 0' }}>
                      <span className="code-lang-label">{comp.lang}</span>
                      <pre className="doc-code-block" style={{ background: '#0e0e0e', border: '1px solid #222', borderRadius: '6px', padding: '12px', overflowX: 'auto', fontSize: '0.8rem', fontFamily: 'monospace' }}>
                        <code>{comp.content}</code>
                      </pre>
                    </div>
                  );
                }
                
                if (comp.type === 'alert') {
                  let alertTitle = "提示";
                  if (comp.alert_type === 'warning') alertTitle = "警告";
                  if (comp.alert_type === 'caution') alertTitle = "注意";
                  if (comp.alert_type === 'important') alertTitle = "重要";
                  if (comp.alert_type === 'tip') alertTitle = "提示";

                  return (
                    <div key={cidx} className={`doc-alert-box alert-${comp.alert_type}`} style={{ margin: '1rem 0', padding: '12px 16px', borderRadius: '8px', borderLeft: '4px solid', background: 'rgba(255,255,255,0.02)' }}>
                      <strong style={{ display: 'block', fontSize: '0.85rem', marginBottom: '4px', textTransform: 'uppercase' }}>
                        {alertTitle}
                      </strong>
                      <span 
                        style={{ fontSize: '0.95rem', lineHeight: 1.6, color: '#f5f5f7' }}
                        dangerouslySetInnerHTML={{ __html: formatContent(comp.content || '') }}
                      />
                    </div>
                  );
                }
                
                if (comp.type === 'list' && comp.items) {
                  return (
                    <ul key={cidx} className="doc-list">
                      {comp.items.map((item, lidx) => (
                        <li key={lidx} dangerouslySetInnerHTML={{ __html: formatContent(item) }} />
                      ))}
                    </ul>
                  );
                }
                
                return null;
              })}
              
            </section>
          ))}
          
        </main>
        
      </div>
    </div>
  );
};
