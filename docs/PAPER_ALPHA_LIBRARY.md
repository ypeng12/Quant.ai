# 可复现的 Alpha 候选库

这次实现因子、标签、训练、持久化、推断和 Lab 展示，不进行策略回测或声称收益改善。
代码实现、输入数据可用、模型已训练、样本外有效是四种不同状态。

## 已实现的范围

| 组件 | 默认输出 | 实现与限制 |
| --- | --- | --- |
| Alpha158 精选 | 18 列 | KMID/KLEN/KMID2/KUP/KLOW/KSFT；ROC/MA/STD/RSV/VMA/CORR，窗口 5、20 |
| Alpha101 精选 | 6 列 | 002、003、004、006、012、101；不依赖缺失的真实 VWAP |
| 截面/同行 | 7 列 | 同时点收益排名、排除自身的同行收益/残差、同组残差、过去窗口 Beta/市场残差、有效同行数 |
| 真实 L1 | 12 列 | 保留原六项，新增原始 OFI、平均半深度、OFI/半深度、与价差和时段正余弦的交互 |
| QI Logistic | 状态模型 | 用 QI 预测下一次不同中间价的向上概率；每次价格变动等权，避免报价密集片段主导训练 |
| Transition Microprice | 状态模型 | 估计 Q/R、下一次价格变动期望、变动后状态转移；默认累加六次价格变动修正 |
| OFI Ridge | 五个预测周期 | 真实报价事件的 QI/OFI/加权中间价/价差输入；1s、5s、30s、1min、5min 中间价标签 |
| 量价 + L1 Ridge | 融合模型 | 相同的五分钟输入与下一根开盘到持有期收盘标签；缺少必需 L1 列时不虚构预测 |

这些输出有相关性，也包含控制变量和数据覆盖诊断。31 个量价输入不等于 31 个独立有效 Alpha。
Ridge、树模型、LightGBM 均可训练；所有尝试记录在 registry，未按这段历史收益挑出赢家。

## 与原文的区别

- [Qlib Alpha158 定义](https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/loader.py)：独立实现精选公式，未导入整个 Qlib。ROC 保留 `delay(close,w)/close` 定义，标准差采用样本标准差。
- [Alpha101](https://arxiv.org/abs/1601.00991)：原研究报告的持有期以天计。本项目这里是**五分钟、每日重置的周期适配**，不宣称复现原文效果。截面排名仅含指定研究股票，ETF 参考输入不参与排名；并列值平均排名，归一化到 (0,1]。窗口缺失保持 NaN。
- [Cont / Kukanov / Stoikov](https://arxiv.org/abs/1011.6402)：新增深度采用区间内 `(bid_size + ask_size)/2` 的平均值。原 `l1_ofi_normalized` 为兼容旧产物仍使用总深度中位数，两个名字不能混淆。报价数量保留供应商单位，不把它与成交股数相加。
- [Gould / Bonart](https://arxiv.org/abs/1512.03492)：QI 的标签是下一次中间价变动，不能用作交易胜率。此处用带正则项的简单 Logistic 基准，并按下一次变动事件加权，属于明确的实现选择。
- [Stoikov 作者实现](https://github.com/sstoikov/microprice)：独立实现状态转移方程。状态是价差 tick 数和等宽 QI 桶；默认 5 桶、1–5 tick 价差、6 次价格变动、对称样本，是可配置实验参数。与作者用训练样本分位数划桶有区别。保存完整矩阵、支持样本数、最后增量和 Q 谱半径。没有无限级数收敛保证；未见状态返回缺失，无可识别转移则报告不足。`tick_size=0.01` 必须按标的报价规格核对。

这里的简单加权中间价仍保留，但与状态转移 Microprice 分开命名。两者都不是可成交价格。

## 数据和时间约定

`paper_bar_alpha.bar_alpha_panel()` 是训练和推断共用的量价入口。输入是带时区的五分钟开盘时间戳，必须等 K 线收盘才可用；`as_of` 会排除未完成 K 线。日内网格显式保留缺口，不压缩滚动窗口。不用全样本标准化或未来数据填缺值。均值和尺度只在训练样本拟合；从未观察到的列会被明确记录为 unused。

当前候选研究池为 21 只普通股票加 SPY/QQQ/SOXX 参考，不含 MSTR、COIN、MARA、IBIT。分组表是版本化的人工行业近似，不是历史 GICS 档案。它不改变券商 watchlist；价格至少 $10、过去 20 日平均成交额至少 $5,000 万的已同意准入仍属于已有选股/组合流程。特征构建不会把固定名单直接视为当日可交易名单。

真实 L1 不从 OHLCV 生成。历史输入采用交易所事件时间，不能验证历史送达延迟；WebSocket 输入采用实际留存的 `received_at`，缺失时拒绝建立到达时间实验。晚到的过期交换时间事件在实验中排除并计数，原始落盘不删除。报价标签不跨日期、无效盘口或超过配置值的事件缺口（默认 30 秒），目标到期时间单独保存。

QI 的成熟时间是首次后续中间价变动；固定时间收益标签取 `t+h` 之后容差内的首个报价（默认 1 秒容差），缺失不补。训练严格要求标签成熟时间 `< trained_before`。历史数据能研究信息关系，无法证明真实延迟条件下可盈利。

## 运行

从项目根目录生成特征，并训练截至 9 月 11 日的模型：

```bash
python3 scripts/build_paper_alpha_library.py \
  --bars reports/platform_universe30_bars_20260913 \
  --output reports/paper_alpha_library_20260913 \
  --train-before '2026-09-12T00:00:00-04:00'
```

输出目录必须不存在，避免覆盖旧实验。省略 `--train-before` 只构建特征；`--models ridge tree lightgbm` 可以显式选模型。可用 `--symbols` 指定并记录研究面板。缺少文件会列出，不虚构行情。

已有真实 L1 留存后，在命令上加 `--l1-dir <capture-root>` 与 `--l1-symbols SNDK TSLA PLTR NVDA`，输出到另一个新目录，即可同时尝试 QI、Microprice、多期限 OFI Ridge 和量价 + L1 Ridge。缺少样本或无法识别的模型各自记录 unavailable，不冒充训练成功。

产物包含因子 parquet、模型 JSON、数据和代码 SHA256、训练截止时刻、缺失列及状态。模型用可检查的 JSON 保存系数/树结构/LightGBM 文本模型，不使用 pickle。`PaperForecast.load(...).forecast(frames, as_of=...)` 使用与训练相同的特征引擎；融合模型另传 `events=`。必须供给模型声明的同一股票面板。默认只输出训练截止之后的预测。

现有统一实验的 `features_for_panel` 新增 `alpha158_subset`、`alpha101_subset`、`cross_sectional`、`paper_library`、`paper_l1`、`paper_combined` 六个入口。原有实验菜单和历史产物保持可识别，不自动将新模型置换为实盘策略。

Lab 的 `/api/research/alpha_library` 展示实现状态，校验固定构建记录及其文件哈希。构建记录完整不等于策略有效。当前 `live_runner` 无需改订单逻辑来完成这轮研究接入；它仍加载原有策略模型。后续若验证通过，再将具体模型、面板、成本和组合规则一起接入实盘，不能只把新特征塞进旧系数。

## 2026-09-13 实际构建记录

`reports/paper_alpha_library_20260913/registry.json` 已通过完整性校验：20 只股票、3 个参考 ETF，BAC 缺少本地行情。生成 31 列量价/截面联合输入，以及 240 份已训练、待验证的模型 JSON（20 股 × 4 种输入组 × Ridge/树/LightGBM）。341 个文件的哈希、输入来源清单、训练代码快照均核对通过。真实 L1 未提供留存目录，四只默认采集股票都明确记录 unavailable，没有生成盘口数据或冒充训练成功。

新增与相关回归测试共 28 项通过；前端 TypeScript/Vite 构建通过。覆盖未来数据扰动、收盘可用时间、缺口、截面排名、成熟标签、源/股票一致性、序列化前后推断、Microprice 转移方程、缺失 L1 及产物篡改。

原 Desktop 工作区出现 macOS `dataless` 云端占位文件读空/超时，本次从已推送的 `efa2997` 在 `/Users/yuliangpeng/Quant-alpha-work` 建立独立可读副本，修改位于 `feat/paper-alpha-library` 分支。没有覆盖原目录中无法读取的文件。

## 下一步验证

固定同一股票池、日期、资金、标签及成本，比较现有模型、精选量价、加入截面、加入真实 L1 的增量。用过去训练的逐日滚动测试与未来留存数据，查看净收益、按日不确定性、IC、换手和各股票归因。已反复研究的日期只用于开发，不作为未触碰测试集。这份构建记录没有任何盈利结论。
