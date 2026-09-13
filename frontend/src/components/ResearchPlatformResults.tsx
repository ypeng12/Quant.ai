import { useEffect, useState } from 'react';
import { API_BASE } from '../config';

type Attribution = { symbol?: string; direction?: string; hour?: number; gross_pnl: number; costs: number; net_pnl: number };
type Trial = {
  candidate: { name: string; features: string; model: string; portfolio: string };
  cost_bps: number; status: string; reason?: string;
  summary?: { net_pnl: number; gross_pnl: number; costs: number; max_drawdown: number; fill_count: number };
  per_symbol?: Record<string, { net_pnl: number; costs: number }>;
  attribution?: { by_symbol: Attribution[]; by_direction: Attribution[]; by_hour: Attribution[] };
  fixed_order_stress_5bps?: { net_pnl?: number };
};
type Research = { evaluation_dates: string[]; symbols: string[]; starting_equity: number; cost_bps_per_side: number[];
  trials: Trial[]; selected_for_live: string | null; registered_at: string; source_matches_workspace: Record<string, boolean> };
const money = (v: number) => v.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const names: Record<string, string> = {
  cash: '现金基准', equal_weight: '日内等权基准', price_ridge: '量价 Ridge', peer_ridge: '同组相对收益 Ridge',
  context_ridge: '时段与隔夜特征 Ridge', context_tree: '时段与隔夜特征 决策树', context_lightgbm: '时段与隔夜特征 LightGBM',
  context_uncertainty: 'Ridge + 预测不确定性', context_common_risk: 'Ridge + 共同风险', context_robust: 'Ridge + 两项组合调整',
  l1_ridge: '真实 L1 Ridge', combined_robust: '真实 L1 + 量价 + 组合调整',
};

export function ResearchPlatformResults() {
  const [dataset, setDataset] = useState('four_two_weeks');
  const [research, setResearch] = useState<Research | null>(null);
  const [error, setError] = useState('');
  const [cost, setCost] = useState(5);
  const [chosen, setChosen] = useState('context_robust');
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/api/research/platform?dataset=${dataset}`, { signal: controller.signal })
      .then(async res => { if (!res.ok) throw new Error(`HTTP ${res.status}`); return res.json(); })
      .then(data => {
        if (controller.signal.aborted) return;
        if (!data.success || data.status !== 'complete') throw new Error(data.reason || '研究产物未通过校验');
        setResearch(data.research);
        setCost(data.research.cost_bps_per_side.includes(5) ? 5 : data.research.cost_bps_per_side[0]);
      }).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, [dataset]);
  const datasetSelector = <label className="flex items-center gap-3 text-sm text-slate-300 mb-4">研究样本
    <select aria-label="研究样本" value={dataset} onChange={e => { setResearch(null); setError(''); setDataset(e.target.value); }} className="bg-slate-900 border border-slate-700 rounded p-2">
      <option value="four_two_weeks">四只股票 · 两周</option><option value="four_recent_week">四只股票 · 最近一周</option><option value="thirty_two_weeks">30 只股票 · 两周</option>
    </select>
  </label>;
  if (error) return <div>{datasetSelector}<p role="alert" className="p-5 text-amber-300">统一研究结果暂不可用：{error}</p></div>;
  if (!research) return <div>{datasetSelector}<p role="status" className="p-5 text-slate-400">正在读取并校验研究记录…</p></div>;
  const trials = research.trials.filter(t => t.cost_bps === cost);
  const selected = trials.find(t => t.candidate.name === chosen);
  const groups = selected?.attribution;
  const symbolRows: Attribution[] = Object.entries(selected?.per_symbol ?? {}).map(([symbol, row]) => (
    { symbol, net_pnl: row.net_pnl, costs: row.costs, gross_pnl: row.net_pnl + row.costs }
  ));
  return <section className="space-y-5 bg-slate-950/60 border border-slate-800 rounded-xl p-5 text-sm text-slate-300">
    {datasetSelector}
    <div>
      <h3 className="font-semibold text-amber-300">统一研究：预测、组合与成本</h3>
      <p className="mt-2">{research.evaluation_dates[0]} 至 {research.evaluation_dates.at(-1)} · {research.evaluation_dates.length} 个交易日 · {research.symbols.join(', ')} · 模拟起始资金 {money(research.starting_equity)}</p>
      <p className="mt-2 text-amber-200">这段历史已用于探索。结果属于历史模拟；未来验证尚无观测，真实 L1 候选仍缺数据。没有候选因本表排名自动进入实盘。</p>
      <p className="mt-2 text-xs text-slate-400">所有候选使用过去交易日训练、下一根开盘成交和日内平仓。成本是每笔单边成交金额的假设扣减，未测得实际冲击、借券或延迟成本。</p>
    </div>
    <label className="flex items-center gap-3">每笔单边成本
      <select aria-label="每笔单边成本" value={cost} onChange={e => setCost(Number(e.target.value))} className="bg-slate-900 border border-slate-700 rounded p-2">
        {research.cost_bps_per_side.map(c => <option key={c} value={c}>{c} bps（{(c / 100).toFixed(2)}%）</option>)}
      </select>
    </label>
    <p className="text-xs text-slate-400">每档成本都重新计算仓位并实际扣减同档成本，因此订单路径可能改变；高成本下收益更高不代表成本能创造收益。</p>
    <div className="overflow-x-auto"><table className="w-full text-left text-xs">
      <thead><tr>{['候选', '毛盈亏', '成本', '净盈亏', '最大回撤', '成交笔数'].map(h => <th key={h} className="p-3 border-b border-slate-700">{h}</th>)}</tr></thead>
      <tbody>{trials.map(t => <tr key={t.candidate.name} className={chosen === t.candidate.name ? 'bg-slate-800/60' : ''}>
        <td className="p-3"><button onClick={() => setChosen(t.candidate.name)} className="text-left text-sky-300 underline decoration-slate-600">{names[t.candidate.name] || t.candidate.name}</button></td>
        {t.status === 'complete' && t.summary ? <>
          <td className="p-3">{money(t.summary.gross_pnl)}</td><td className="p-3">{money(t.summary.costs)}</td>
          <td className={`p-3 ${t.summary.net_pnl >= 0 ? 'text-emerald-300' : 'text-rose-300'}`}>{money(t.summary.net_pnl)}</td>
          <td className="p-3">{(t.summary.max_drawdown * 100).toFixed(2)}%</td><td className="p-3">{t.summary.fill_count}</td>
        </> : <td colSpan={5} className="p-3 text-amber-300">无法评估：{t.reason}</td>}
      </tr>)}</tbody>
    </table></div>
    {groups && <div className="space-y-3">
      <h4 className="font-semibold">{names[chosen] || chosen}：盈亏归因</h4>
      <div className="grid gap-4 md:grid-cols-2">
        {([['股票', symbolRows], ['持仓方向', groups.by_direction]] as const).map(([title, rows]) => <div key={title}>
          <table className="w-full text-xs text-left"><thead><tr><th className="p-2">{title}</th><th className="p-2">毛盈亏</th><th className="p-2">成本</th><th className="p-2">净盈亏</th></tr></thead>
            <tbody>{rows.map((r, i) => <tr key={i}><td className="p-2">{r.symbol || (r.direction === 'long' ? '多头' : '空头')}</td><td className="p-2">{money(r.gross_pnl)}</td><td className="p-2">{money(r.costs)}</td><td className="p-2">{money(r.net_pnl)}</td></tr>)}</tbody>
          </table>
        </div>)}
      </div>
    </div>}
    <p className="text-xs text-slate-500">文件和输入数据校验通过。工作区代码{Object.values(research.source_matches_workspace).every(Boolean) ? '与本次研究一致' : '已有后续变更；本表对应归档版本'}。{research.symbols.length} 只股票和 {research.evaluation_dates.length} 个交易日仍不能证明稳定 Alpha；共同风险为统计因子，尚未验证行业风险。</p>
  </section>;
}
