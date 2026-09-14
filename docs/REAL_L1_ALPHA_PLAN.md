# 真实 L1 Alpha 实施与验证计划

更新：2026-09-13。当前默认非加密观察池为 SNDK、TSLA、PLTR、NVDA；MSTR 不进入当前交易、L1 采集或普通股票研究池。历史实验中的 MSTR 记录保留用于复现，不能改写为 PLTR 的结果。

## 论文给项目的直接收获

Cont、Kukanov 与 Stoikov 使用 2010 年一个月、50 只美国股票的合并 TAQ Level-1 数据，研究十秒级**同区间**中间价变化与最优买卖价队列变化。论文定义每个报价事件的贡献：买价上升或买一数量增加提高 OFI，买价下降或买一数量减少降低 OFI；卖价下降或卖一数量增加降低 OFI，卖价上升或卖一数量减少提高 OFI。区间 OFI 是这些事件贡献之和。

主要结果是同区间价格变化与 OFI 近似线性，50 股平均解释度约 65%；价格冲击系数随最优档平均深度增加而下降。成交量或成交方向失衡的解释力明显弱于包含报价新增、撤单和成交共同效果的 OFI。原文：[The Price Impact of Order Book Events](https://arxiv.org/pdf/1011.6402)。

这些发现支持项目保留真实 L1 报价更新并计算 OFI，也支持按股票、时段和市场深度标准化。它们不证明 OFI 可以预测未来五分钟收益；论文核心回归使用的是同一区间 OFI 与同一区间价格变化。项目必须另外测试特征形成以后 1 秒、5 秒、30 秒、1 分钟和 5 分钟的未来可执行收益。

## 当前可立即执行的数据路线

免费 Alpaca 实时流是 IEX 单一交易所，适合连续采集和工程验证。历史端点允许查询结束时间至少早于当前 15 分钟的 SIP 数据，能在账户权限允许时补充更完整的多交易所历史 Level-1。SIP 历史数据可以减少等待，但不能替代未来 shadow 验证。官方区别说明：[Alpaca Market Data FAQ](https://docs.alpaca.markets/docs/market-data-faq)。

实时 IEX 采集：

```bash
python3 scripts/capture_alpaca_l1.py \
  --symbols SNDK TSLA PLTR NVDA \
  --feed iex
```

立即补最近十个交易日的历史 SIP 报价和成交时，应分别落盘，避免混淆数据类型：

```bash
python3 scripts/download_research_history.py \
  --symbols SNDK TSLA PLTR NVDA \
  --start 2026-08-31T13:30:00Z \
  --end 2026-09-11T20:00:00Z \
  --feed sip --kind quotes \
  --output backend/data/l1_history_sip_quotes_20260831_20260911

python3 scripts/download_research_history.py \
  --symbols SNDK TSLA PLTR NVDA \
  --start 2026-08-31T13:30:00Z \
  --end 2026-09-11T20:00:00Z \
  --feed sip --kind trades \
  --output backend/data/l1_history_sip_trades_20260831_20260911
```

历史下载器逐页保存原始响应、哈希、事件数量和归一化 JSONL，不把全部逐笔数据同时留在内存。下载未完成时 manifest 标记为 `incomplete`，研究加载器会拒绝使用。

实时采集满若干交易日后运行质量审计：

```bash
python3 scripts/audit_l1_capture.py \
  --input backend/data/l1_capture \
  --symbols SNDK TSLA PLTR NVDA \
  --output reports/l1_quality_20260925
```

审计输出逐股票逐日事件数、Quote/Trade 比例、分钟覆盖、重复事件、无效或交叉报价、价差分布、事件间隔以及 WebSocket 接收延迟。五到十天只用于判断采集链路和数据质量。

## Alpha 验证顺序

1. 固定股票、日期、数据源、预测时点与成本定义，禁止看完收益以后删除失败日期或股票。
2. 建立零预测、价格成交量 Ridge 和简单动量基准。
3. 分别测试 OFI、OFI/平均深度、Quote Imbalance、Microprice 偏离、Signed Trade Imbalance 和价差状态。
4. 比较 L1 单因子、L1 Ridge、价格成交量基准和价格成交量加 L1，保留所有失败候选。
5. 对每个特征测量不同未来周期的 Pearson IC、Spearman IC、方向准确率、换手和成本后收益，并按股票、日期及时段报告。
6. 置信区间按交易日聚类计算，避免把同一天大量相邻事件误当成独立样本。
7. 研究秒级执行用途：在组合目标不变的情况下比较市价、被动限价和短时间等待，报告成交率、相对到达价滑点、未成交机会成本和成交后价格变化。
8. 历史 SIP 只用于开发和回顾实验；真实 IEX 连续数据形成后登记未来 shadow 样本。只有增量效果在未参与开发的未来区间仍存在，才提出接入实时策略的具体变更。

## 共享对话中候选研究的取舍

- **Queue Imbalance**：已以 `l1_quote_imbalance` 实现，需要复现下一次中间价变动的 Logistic 基准，不将因子值直接转为买卖阈值。
- **OFI**：基础公式已实现，将新增原始 OFI、深度标准化 OFI 与 spread/depth 交互的消融实验。
- **Microprice**：已实现最优一档数量加权价格；它不是 Stoikov 完整状态转移 Microprice 模型。先证明简单版本有增量，再实现完整版。
- **Alpha158**：当前量价特征已覆盖历史收益、波动、量能、K 线结构和相对价格的一部分概念，但不是 Alpha158 复制。只在扩大股票截面和明确持有期后，按组加入少量可解释候选。
- **Alpha101**：更适合日级或多日截面研究。项目不会将 101 个公式全部塞入五分钟模型，避免在小样本上加速过拟合。
- **DeepLOB**：需要多档 L2 历史序列。免费 Alpaca L1 只有最优一档，现在不具备合格输入，因此不列入近期实现。

旧 `cross_sectional_lead_lag.py` 原型在数据不足时返回固定相关系数和基点差，并把未对齐的价格列表称为 500ms 套利。该输出已改为明确 `unavailable`，直到存在带时间戳、同步且可回放的事件数据。

## 当前状态

- OFI、Microprice、Quote Imbalance 和 Signed Trade Imbalance 的基础实现已经存在。
- L1 历史分页下载已存在并已调整为逐页归一化，适合更大的逐笔数据量。
- 数据质量审计脚本已存在。
- 2026-09-13更新：已实际验证历史SIP读取权限和实时IEX四股订阅，并启用本机后台采集；已留存真实IEX历史事件。当前可读运行数据、研究命令和停止方法见 [L1_OPERATIONS.md](L1_OPERATIONS.md)。本次完整四股研究使用2026-09-11常规交易时段；历史数据与未来采集分别保存。
- 当前没有经过样本外验证的 L1 盈利结果，也没有改动 `live_runner.py` 的交易逻辑。
