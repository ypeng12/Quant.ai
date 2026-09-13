export interface ResearchWindow {
  starting_equity?: number;
  net_pnl: number;
  net_return?: number;
  max_drawdown?: number;
  costs: number;
}

export interface PolicyResearchSummary {
  generated_at: string;
  evaluation_start: string;
  evaluation_end: string;
  selection_cutoff: string;
  starting_equity: number;
  cost_bps_per_side: number;
  selected_spec: { name: string; feature_set: string; horizon_bars: number; risk_aversion: number };
  trial_count: number;
  portfolio: { two_week: ResearchWindow; recent_week: ResearchWindow; recent_week_reset?: ResearchWindow };
  per_ticker: Record<string, { two_week: ResearchWindow; recent_week: ResearchWindow; recent_week_reset?: ResearchWindow }>;
  fixed_orderflow_5bps_stress?: ResearchWindow;
  benchmarks?: { equal_weight_session: ResearchWindow };
  trials: { id: string; spec: { name: string }; validation_net_return: number; evaluation_net_return: number; selected: boolean }[];
}

const money = (n: number | undefined) => typeof n === 'number' && Number.isFinite(n)
  ? n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }) : '未计算';
const percent = (n: number | undefined) => typeof n === 'number' && Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : '未计算';
const cell = { padding: '9px 12px', borderBottom: '1px solid #334155', textAlign: 'right' as const };

export function PolicyResearchResults({ research, ticker }: { research: PolicyResearchSummary; ticker?: string }) {
  const selected = ticker ? research.per_ticker[ticker] : null;
  const recent = research.portfolio.recent_week_reset || research.portfolio.recent_week;
  const recentTicker = selected?.recent_week_reset || selected?.recent_week;
  return <section style={{ padding: 20, marginBottom: 24, background: '#0f172a', border: '1px solid #334155', borderRadius: 12, color: '#cbd5e1' }}>
    <h3 style={{ marginTop: 0, color: '#f8fafc' }}>交易策略研究 · {research.selected_spec.name}</h3>
    <p>评估日期 {research.evaluation_start} 至 {research.evaluation_end}；候选选择仅使用 {research.selection_cutoff} 及以前的数据。</p>
    <p>组合初始本金 {money(research.starting_equity)}；单边成本 {research.cost_bps_per_side} bps；共 {research.trial_count} 个候选。四股共享资金。</p>
    <p>最近一周{research.portfolio.recent_week_reset ? `单独从 ${money(recent.starting_equity)} 开始重算` : `为两周连续账本的末周切片，期初资金 ${money(recent.starting_equity)}`}。</p>
    <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
      <thead><tr><th style={cell}>结果范围</th><th style={cell}>最近一周净盈亏</th><th style={cell}>两周净盈亏</th><th style={cell}>两周成本</th></tr></thead>
      <tbody>
        <tr><td style={cell}>四股组合</td><td style={cell}>{money(recent.net_pnl)}</td><td style={cell}>{money(research.portfolio.two_week.net_pnl)}</td><td style={cell}>{money(research.portfolio.two_week.costs)}</td></tr>
        {selected && <tr><td style={cell}>{ticker} 贡献</td><td style={cell}>{money(recentTicker?.net_pnl)}</td><td style={cell}>{money(selected.two_week.net_pnl)}</td><td style={cell}>{money(selected.two_week.costs)}</td></tr>}
      </tbody>
    </table></div>
    <p>组合两周收益率 {percent(research.portfolio.two_week.net_return)}；5分钟边界最大回撤 {percent(Math.abs(research.portfolio.two_week.max_drawdown ?? 0))}。</p>
    {research.fixed_orderflow_5bps_stress && <p>相同订单按每边 5 bps 成本计价，两周净盈亏 {money(research.fixed_orderflow_5bps_stress.net_pnl)}。这是成本敏感性分析；提高成本后需重新检查资金约束，不能当作另一套可执行策略。</p>}
    {research.benchmarks && <p>四股等权日内持有基准，两周净盈亏 {money(research.benchmarks.equal_weight_session.net_pnl)}。</p>}
    <details><summary style={{ cursor: 'pointer', color: '#7dd3fc' }}>查看全部候选与选择依据</summary>
      <div style={{ overflowX: 'auto' }}><table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead><tr><th style={cell}>候选</th><th style={cell}>之前验证期净收益</th><th style={cell}>随后两周净收益</th><th style={cell}>选定状态</th></tr></thead>
        <tbody>{research.trials.map(trial => <tr key={trial.id}>
          <td style={cell}>{trial.spec.name}</td><td style={cell}>{percent(trial.validation_net_return)}</td><td style={cell}>{percent(trial.evaluation_net_return)}</td><td style={cell}>{trial.selected ? '按之前验证期选定' : '对照'}</td>
        </tr>)}</tbody>
      </table></div>
    </details>
    <p style={{ fontSize: 12, color: '#94a3b8' }}>这是历史逐日模拟，使用完整K线后的下一根开盘价与成本假设；不代表实际成交或未来收益。该日期区间此前已研究过，不能称为从未看过的最终检验集。</p>
  </section>;
}
