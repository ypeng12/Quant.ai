import { useEffect, useState } from 'react';
import { API_BASE } from '../config';

type Library = {
  entries: { id: string; name: string; features: number | null; data: string; purpose: string; source: string | null }[];
  report_status: string; reason: string | null;
  report: null | {
    symbols: string[]; missing_symbols: string[];
    models: { status: string; symbol: string; family: string; estimator: string }[];
    l1: Record<string, { status: string; reason?: string }>;
  };
};

export function PaperAlphaLibrary() {
  const [library, setLibrary] = useState<Library | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API_BASE}/api/research/alpha_library`, { signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
      .then(setLibrary).catch(e => { if (e.name !== 'AbortError') setError(String(e.message)); });
    return () => controller.abort();
  }, []);
  return <section className="mb-5 rounded-xl border border-slate-700 bg-slate-950/60 p-5 text-sm text-slate-300">
    <h3 className="font-semibold text-sky-300">Alpha 候选库 · 实现与数据状态</h3>
    <p className="my-2 text-amber-200">这些是待验证的研究候选。公式数量、训练完成和样本外收益是不同的事情；本次构建不计算盈利。</p>
    {error && <p role="alert">候选库暂不可用：{error}</p>}
    {!library && !error && <p role="status">读取候选库…</p>}
    {library && <>
      <div className="overflow-x-auto"><table className="w-full text-left text-xs">
        <thead><tr>{['候选', '输出数量', '所需数据', '用途'].map(h => <th key={h} className="p-2">{h}</th>)}</tr></thead>
        <tbody>{library.entries.map(entry => <tr key={entry.id} className="border-t border-slate-800">
          <td className="p-2">{entry.source ? <a href={entry.source} target="_blank" rel="noreferrer" className="text-sky-300 underline">{entry.name}</a> : entry.name}</td>
          <td className="p-2">{entry.features ?? '状态模型'}</td><td className="p-2">{entry.data}</td><td className="p-2">{entry.purpose}</td>
        </tr>)}</tbody>
      </table></div>
      <p className="mt-3">量价窗口按五分钟 K 线计数，每日重置；这是周期适配，不是原论文日频结果。</p>
      {library.report_status !== 'complete' && <p className="mt-2 text-amber-200">构建记录：{library.reason}</p>}
      {library.report && <div className="mt-3 space-y-2">
        <p>已读取行情：{library.report.symbols.join('、')}</p>
        {library.report.missing_symbols.length > 0 && <p>缺少行情：{library.report.missing_symbols.join('、')}</p>}
        <p>已训练、待验证的模型产物：{library.report.models.filter(m => m.status === 'trained_unvalidated').length} 个（按股票、因子组及模型分别计数，不代表这么多个有效 Alpha）。</p>
        <p>真实 L1：{Object.entries(library.report.l1).map(([s, status]) => `${s}：${status.status === 'unavailable' ? status.reason || '数据不足' : '已生成特征，效果待验证'}`).join('；')}</p>
      </div>}
    </>}
  </section>;
}
