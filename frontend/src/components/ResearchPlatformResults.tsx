import { useEffect, useState } from 'react';
import { API_BASE } from '../config';
import { PaperAlphaLibrary } from './PaperAlphaLibrary';

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
  trials: Trial[]; selected_for_live: string | null; registered_at: string; source_matches_workspace: Record<string, boolean>;
  unverified_assumptions?: string[]; selected_for_future_paper?: string; retrospective_best?: string;
  traded_symbols?: string[];
  stock_selection?: { day: string; validation_dates: string[]; selections: Record<string, { model: string; scores_mse_bps2: Record<string, number> }> }[];
  liquidity_rules?: { min_price: number; min_adv: number; min_market_cap: number; lookback_sessions: number };
  universe_admission?: { day: string; stocks: Record<string, { eligible: boolean; reason: string; last_price: number | null; adv: number | null; market_cap: number | null }> } };
const money = (v: number) => v.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
const names: Record<string, string> = {
  cash: '现金基准', equal_weight: '日内等权基准', price_ridge: '量价 Ridge', peer_ridge: '同组相对收益 Ridge',
  context_ridge: '时段与隔夜特征 Ridge', context_tree: '时段与隔夜特征 决策树', context_lightgbm: '时段与隔夜特征 LightGBM',
  context_uncertainty: 'Ridge + 预测不确定性', context_common_risk: 'Ridge + 共同风险', context_robust: 'Ridge + 两项组合调整',
  l1_ridge: '真实 L1 Ridge', combined_robust: '真实 L1 + 量价 + 组合调整',
  four_tree_control: '原四股树模型对照', largecap_four_tree: '准入筛选四股树模型', largecap_equal: '大市值等权基准',
  largecap_tree: '大市值树模型', largecap_calibrated: '大市值树与 Ridge 校准组合',
  largecap_integrated: '大市值校准模型与组合风险', largecap_integrated_25pct: '大市值组合风险 · 单股上限 25%',
  liquid_dynamic_70: '不设市值下限 · 动态配仓', four_concentrated_95: '原四股 · 单股上限 95%',
  liquid_single_95: '不设市值下限 · 单股 95% 或现金', liquid_dynamic_95_g25: '不设市值下限 · 更积极配仓',
  market_tree_h1: '大盘/行业输入 · 5分钟树模型', market_tree_h6: '大盘/行业输入 · 30分钟树模型',
  market_ridge_h6: '大盘/行业输入 · 30分钟 Ridge', market_tree_h12: '大盘/行业输入 · 60分钟树模型',
  market_curve_ridge: '收益期限结构 · 30分钟多期配仓',
  noncrypto_context_tree: '非加密四股 · 量价与时段树模型', noncrypto_market_tree: '非加密四股 · 大盘/行业树模型',
  noncrypto_market_ridge: '非加密四股 · 大盘/行业 Ridge', noncrypto_stock_selector: '非加密四股 · 按股票选择模型',
  market_tree: '大盘/行业树模型', market_ridge: '大盘/行业 Ridge',
  conditional_equal: '不使用 ML · 日内等权', conditional_ridge_control: '当前 Ridge 对照',
  conditional_state_h1: '量能/波动状态交互 · 5分钟 Ridge', conditional_state_h6: '量能/波动状态交互 · 30分钟 Ridge',
  incremental_equal: '日内等权对照', incremental_control: '原条件 Ridge · 冻结对照',
  incremental_slot: '加入历史同一时段收益', incremental_gap: '加入隔夜与日内交互',
  incremental_range: '加入区间结构与方向波动', incremental_all: '三组新增信息合并',
};

export function ResearchPlatformResults() {
  const [dataset, setDataset] = useState('noncrypto_two_weeks');
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
        setChosen(data.research.selected_for_future_paper || (dataset.startsWith('incremental_') ? 'incremental_control' : dataset === 'conditional_two_weeks' ? 'conditional_state_h1' : dataset === 'noncrypto_two_weeks' ? 'noncrypto_stock_selector' : dataset === 'direction_two_weeks' ? 'market_curve_ridge' : data.research.liquidity_rules ? (data.research.liquidity_rules.min_market_cap === 0 ? 'liquid_dynamic_70' : 'largecap_integrated') : 'context_robust'));
      }).catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    return () => controller.abort();
  }, [dataset]);
  const datasetSelector = <label className="flex items-center gap-3 text-sm text-slate-300 mb-4">研究样本
    <select aria-label="研究样本" value={dataset} onChange={e => { setResearch(null); setError(''); setDataset(e.target.value); }} className="bg-slate-900 border border-slate-700 rounded p-2">
      <option value="noncrypto_two_weeks">非加密四股 · 逐股模型选择 · 两周</option>
      <option value="conditional_two_weeks">论文启发实验 · 条件动量与无 ML 对照</option>
      <option value="incremental_two_weeks">新增 Alpha 消融比较 · 8/31—9/11</option>
      <option value="incremental_earlier">新增 Alpha 较早区间检查 · 8/24—8/28</option>
      <option value="four_two_weeks">四只股票 · 两周</option><option value="four_recent_week">四只股票 · 最近一周</option><option value="thirty_two_weeks">30 只股票 · 两周</option>
      <option value="extended_two_weeks">Alpha 扩展实验 · 27 个候选 · 两周</option>
      <option value="largecap_two_weeks">主流大市值股票 · 动态配仓 · 两周</option>
      <option value="active_two_weeks">积极配仓与单股集中对照 · 两周</option>
      <option value="direction_two_weeks">四股方向模型修改 · 大盘/行业与多期配仓</option>
    </select>
  </label>;
  if (error) return <div><PaperAlphaLibrary />{datasetSelector}<p role="alert" className="p-5 text-amber-300">统一研究结果暂不可用：{error}</p></div>;
  if (!research) return <div><PaperAlphaLibrary />{datasetSelector}<p role="status" className="p-5 text-slate-400">正在读取并校验研究记录…</p></div>;
  const trials = research.trials.filter(t => t.cost_bps === cost);
  const selected = trials.find(t => t.candidate.name === chosen);
  const groups = selected?.attribution;
  const symbolRows: Attribution[] = Object.entries(selected?.per_symbol ?? {}).map(([symbol, row]) => (
    { symbol, net_pnl: row.net_pnl, costs: row.costs, gross_pnl: row.net_pnl + row.costs }
  ));
  return <section className="space-y-5 bg-slate-950/60 border border-slate-800 rounded-xl p-5 text-sm text-slate-300">
    <PaperAlphaLibrary />
    {datasetSelector}
    <div>
      <h3 className="font-semibold text-amber-300">统一研究：预测、组合与成本</h3>
      <p className="mt-2">{research.evaluation_dates[0]} 至 {research.evaluation_dates.at(-1)} · {research.evaluation_dates.length} 个交易日 · {research.symbols.join(', ')} · 模拟起始资金 {money(research.starting_equity)}</p>
      {research.traded_symbols && <p className="mt-2">交易股票：{research.traded_symbols.join(', ')}。其余行情仅作参考输入。</p>}
      <p className="mt-2 text-amber-200">这段历史已用于探索。本表仅展示历史模拟，未来表现与真实 L1 结果需单独验证。没有候选因本表排名自动进入实盘。</p>
      <p className="mt-2 text-xs text-slate-400">所有候选使用过去交易日训练、下一根开盘成交和日内平仓。成本是每笔单边成交金额的假设扣减，未测得实际冲击、借券或延迟成本。</p>
      {research.selected_for_future_paper && <p className="mt-2">按前五日规则选出的未来研究候选：{research.selected_for_future_paper}。全区间事后最高：{research.retrospective_best}。两者均未证明未来收益。</p>}
      {research.unverified_assumptions?.map(item => <p key={item} className="mt-2 text-xs text-amber-200">{item}</p>)}
    </div>
    {research.liquidity_rules && <p className="text-amber-200">研究准入：股价至少 {money(research.liquidity_rules.min_price)}，前 {research.liquidity_rules.lookback_sessions} 个交易日日均成交额至少 {money(research.liquidity_rules.min_adv)}，{research.liquidity_rules.min_market_cap > 0 ? `当前市值至少 ${money(research.liquidity_rules.min_market_cap)}` : '不设市值规模门槛，仍须有有效证券属性'}，限审核过的 NYSE / Nasdaq 普通股与 ADR。大市值不代表低风险；当前研究池未还原历史成分股。</p>}
    {research.universe_admission && <details>
      <summary className="cursor-pointer text-sky-300">{research.universe_admission.day} 准入明细 · {Object.values(research.universe_admission.stocks).filter(s => s.eligible).length} 只符合条件</summary>
      <div className="overflow-x-auto"><table className="w-full text-xs text-left"><thead><tr>{['股票', '状态', '前收盘', '日均成交额', '当前市值'].map(h => <th key={h} className="p-2">{h}</th>)}</tr></thead>
        <tbody>{Object.entries(research.universe_admission.stocks).map(([s, r]) => <tr key={s}><td className="p-2">{s}</td><td className="p-2">{r.eligible ? '符合条件' : ({ small_or_unknown_market_cap: '市值不足或未知', low_price: '股价不足', low_dollar_volume: '成交额不足', incomplete_prior_sessions: '历史数据不完整' }[r.reason] || r.reason)}</td><td className="p-2">{r.last_price === null ? '缺数据' : money(r.last_price)}</td><td className="p-2">{r.adv === null ? '缺数据' : money(r.adv)}</td><td className="p-2">{r.market_cap === null ? '缺数据' : money(r.market_cap)}</td></tr>)}</tbody>
      </table></div>
    </details>}
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
    {chosen === 'noncrypto_stock_selector' && research.stock_selection && <details open>
      <summary className="cursor-pointer text-sky-300">逐日逐股模型选择依据</summary>
      <p className="mt-2 text-xs text-slate-400">每只股票独立比较前三种模型在此前五个交易日的样本外预测误差，选日均平方误差最低者。不是按当天或两周事后利润挑选；误差更低也不保证净收益更高。</p>
      <div className="overflow-x-auto"><table className="w-full text-xs text-left"><thead><tr>{['交易日', '已完成验证区间', '股票', '选用模型', '日均平方误差（bps²）'].map(h => <th key={h} className="p-2">{h}</th>)}</tr></thead>
        <tbody>{research.stock_selection.flatMap(day => Object.entries(day.selections).map(([s, r]) => <tr key={`${day.day}-${s}`}><td className="p-2">{day.day}</td><td className="p-2">{day.validation_dates[0]} — {day.validation_dates.at(-1)}</td><td className="p-2">{s}</td><td className="p-2">{names[r.model] || r.model}</td><td className="p-2">{r.scores_mse_bps2[r.model].toFixed(2)}</td></tr>))}</tbody>
      </table></div>
    </details>}
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
    <p className="text-xs text-slate-500">文件和输入数据校验通过。工作区代码{Object.values(research.source_matches_workspace).every(Boolean) ? '与本次研究一致' : '已有后续变更；本表对应归档版本'}。{research.symbols.length} 个行情标的（扩展实验包含参考资产）和 {research.evaluation_dates.length} 个交易日仍不能证明稳定 Alpha；行业参考映射也需未来检验。</p>
  </section>;
}
