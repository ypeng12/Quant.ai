# 真实 L1 与现有 Alpha：接入和取舍

本次实现数据采集、因果诊断和研究接口。`live_runner.py` 尚未调用新接口；新代码不提交订单。已有 UI、README 和交易规则保持原样。

## 先区分三个目标

| 层 | 要回答的问题 | 本次实现与边界 |
|---|---|---|
| 主 Alpha | 下一持仓周期的预期收益是多少？ | 接受已有 forecast 的收益、股票顺序、协方差，不重新编造评分。 |
| L1 预测 | 当前真实报价是否增加未来价格预测信息？ | QI、OFI、加权微价；按 1 秒、5 秒、30 秒、1 分钟、5 分钟分别比较。 |
| 组合与执行 | 持有多少、调整多少、何时成交最合算？ | 提供对齐的记录和候选接口；本次不声称已完成成交成本校准或自动订单融合。 |

QI 的“下一次中间价向上概率”、Microprice 的价格估计和五分钟预期收益有不同单位、目标与周期，不能相加成一个任意评分。简单加权微价与状态转移 Microprice 也不是同一个模型。

免费 IEX 提供单个交易所的数据；SIP 汇总多个交易所。IEX 买卖价差和中间价不等于全市场 NBBO，更不能直接当作券商实际成交价格。来源：[Alpaca Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)。

## 本次代码怎样接到现有逻辑旁边

`backend/app/research/l1_policy_overlay.py` 的 `build_l1_policy_record` 接受实际 base forecast，记录：

- 原始预期收益和协方差，保持股票顺序。
- 截止决策时刻可见的真实 L1、完整五分钟桶、最新有效报价及其时间。
- 历史 exchange clock 或实时 recorded arrival clock；数据来源、feed、数量单位。
- QI、Microprice、各周期 L1 Ridge 的独立输出及其明确预测目标。
- 可选的、已拟合且目标兼容的融合候选。未提供融合模型时 `candidate_mu=null`，`active_forecast=base_mu`。

L1 缺失、过期、最新盘口无效、模型尚未训练成熟或来源不匹配，只改变相应诊断的可用状态。它们不暂停原策略，也不增加静态交易否决条件。

融合模型必须显式声明目标收益定义、预测周期、股票顺序、特征版本、时钟、来源、训练截止和最后训练标签的成熟时间。元数据通过仅说明接口兼容，不代表预测有效。候选结果始终与原预测分开；没有默认为 L1 分配某个固定权重。

离线记录工具：

```bash
python3 scripts/record_l1_policy_context.py \
  --forecast /path/to/actual_forecast.json \
  --input /path/to/completed_quotes /path/to/completed_trades \
  --feed iex --source alpaca_stock_historical \
  --max-quote-age 1s --output /path/to/new_context.json
```

forecast JSON 必须包含：`decision_time`、`target`、`horizon_seconds`、`symbols`、`mu`、`covariance`、`return_units="decimal_gross_return"`、`model_trained_before`、`last_training_label_end`。时间均须有时区。工具记录输入哈希；它不会独立验证调用者提供的预测训练血缘，也不会捏造基线预测来演示下单。该工具适合完成落盘后的离线诊断，不是逐笔运行的在线热路径。

## 怎样找到 tradeoff

`scripts/research_l1_tradeoff.py` 将同一股、同一时间、同一未来收益标签下的五组候选放在一起：

1. 零收益预测，检查复杂模型是否连简单基准都不如。
2. 过去中间价收益 Ridge。
3. QI 单独 Ridge。
4. QI、OFI、简单加权微价、价差及交互项 Ridge。
5. 过去中间价收益＋上述 L1 特征 Ridge。

这里的价格基准只使用过去中间价收益，**不是当前交易系统完整量价/截面 Ridge**，也不包含成交方向、状态转移 Microprice 或那套 31 列研究特征。因此这一步只能判断是否值得继续研究，不能宣布原实盘策略已经提升。

决策网格每 5 秒一次。特征只取决策时刻以前已知信息；未来标签从 `decision_time + horizon` 开始，不能从稍早的最后报价时间开始。不同模型共用有效样本，归一化只拟合训练段；训练标签必须在训练截止前成熟。跨日、重连、异常盘口、报价间隙和过期数据会按明确规则标记或隔离。

单日数据：上午训练、下午诊断。多日数据：只用此前日期训练，后一天测试。长周期标签在网格上重叠，不能把每一行当独立统计试验。本次全部尝试都保留，不按测试收益自动挑选或上线。

输出包括预测误差、IC、Rank IC、非零目标方向准确率、零收益比例、覆盖率、逐时段结果以及带训练截止的预测 CSV。成本场景只记录预测幅度超过假设来回成本的比例，以及相邻信号方向变化；它们不是可执行交易盈亏、实际换手或已节省滑点。

```bash
python3 scripts/research_l1_tradeoff.py \
  --input "$HOME/.local/share/quant-l1/data/history_iex_20260911_quotes" \
  --symbols SNDK TSLA PLTR NVDA --sessions 2026-09-11 \
  --horizons 1s 5s 30s 1min 5min \
  --costs 2 5 --output /path/to/new_tradeoff_report
```

## 后续进入资金分配的依据

要比较原策略与融合策略，须留存原模型的真实时点预测，并在相同可执行收益目标下训练 `base_mu + L1` 的修正模型。让拟合结果决定 L1 是否有增量，不手填融合百分比。

组合比较应共同考虑预期收益、协方差、预测误差与调仓成本，记录目标仓位及其变化。执行比较还必须包括真实成交、未成交机会成本、等待时长、逆向选择和价差来源；把市价改成限价并不能自动证明成本下降。假设成本可先作为敏感性分析，但不能写成实际券商费用。

研究输出必须区分“预测改善”“仓位分配改善”和“成交改善”。本次 `selected_for_live=null`；后续接入 `live_runner` 时应提供具体调用位置和行为变化供审阅。
