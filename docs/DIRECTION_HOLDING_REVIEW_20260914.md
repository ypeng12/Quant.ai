# 方向、持仓、真实 L1 接入审阅 — 2026-09-14

本地实现与历史诊断完成；所有新增候选均未自动上线。GitHub / Hugging Face 的线上模型仍为此前版本。
本次新增特征没有证明稳定盈利。改善主要体现在减少反手和模拟摩擦；保留所有失败候选，不以历史最高收益自动选择实盘模型。

## 已实现的六项

1. **统一 Alpha 输入**：恢复 31 列量价/截面特征引擎，补市场和时段交互得到 58 列候选；离线与运行器共用特征函数。不是 58 个已验证 Alpha。
2. **多周期方向**：每股分别预测未来 5/15/30/60 分钟可执行收益；以前五个交易日的样本外预测做收益校准。
3. **持仓与反手**：考虑收益期限、联合协方差和逐段调仓成本，只执行规划的第一步；不设固定最低持仓时间、不因亏损锁死股票。
4. **量能与真实 L1**：同一时段历史成交量归一化；真实 IEX OFI、QI、微价、成交方向与交互特征，可学习基础模型的下一周期残差。没有机构身份推断。
5. **成本核对**：模拟滑点/价差假设与实际费用分开；只读活动及成交前报价审计已运行，4 条成交样本不能决定统一实际成本。
6. **组合与模型覆盖**：SNDK、TSLA、PLTR、NVDA 均生成模型；SPY、QQQ、SOXX 仅供参考。保留已授权的价格/流动性准入，读取真实可借券状态，复用整数股数和券商对账链。

## 两周历史诊断

2026-08-31 至 2026-09-14，共 10 个交易日。初始资金 $47,006.42，日与日之间按模拟净值复利；下一根开盘全额成交、15:55 平仓、期初无库存。外部账本单边摩擦假设 5 bps，不是已证实的 Alpaca 手续费。
除名称含 policy_cost5 的候选内部规划也为 5 bps，其余模型沿用 2 bps 规划假设。历史区间已反复研究，不是未触碰测试集。

| 候选 | 毛模拟盈亏 | 假设摩擦 | 净模拟盈亏 | 反手次数 | 平均持仓分钟 |
|---|---:|---:|---:|---:|---:|
| legacy_refit_h1 | $3,109.95 | $4,772.74 | $-1,662.78 | 218 | 39.4 |
| paper31_h1 | $-3,676.03 | $6,656.45 | $-10,332.48 | 317 | 26.1 |
| context_h1 | $-3,186.85 | $8,006.99 | $-11,193.85 | 335 | 22.0 |
| context_curve | $-3,504.08 | $7,901.15 | $-11,405.23 | 330 | 22.0 |
| equal_weight_hold | $1,717.20 | $447.87 | $1,269.33 | 0 | 385.0 |
| simple_trend | $-518.34 | $1,448.66 | $-1,967.00 | 92 | 115.1 |
| calibrated_legacy_curve | $1,562.96 | $3,900.84 | $-2,337.88 | 116 | 50.3 |
| calibrated_context_curve | $1,397.08 | $5,068.48 | $-3,671.40 | 163 | 39.2 |
| calibrated_legacy_curve_policy_cost5 | $902.66 | $2,287.51 | $-1,384.86 | 43 | 81.6 |

相对统一标签重训的旧特征对照，校准＋5 bps 规划的净结果改善 $277.93，反手减少 175 次。但仍净亏，且低于等权持有基准。不能据此扩大仓位或宣称策略获利。

旧特征对照使用本次统一的 next-open → next-open 标签逐日重训，包含 PLTR；它不等同于线上冻结的原 12 特征产物。不能混用两者的结果。
预测误差 CSV 中的 forecast_metrics 是原始收益曲线预测，校准后的交易路径见 decisions.json；没有把原始 IC 冒充校准后 IC。

## 9/14 同资金独立回放

| 候选 | 净模拟盈亏 |
|---|---:|
| calibrated_legacy_curve | $-76.13 |
| calibrated_context_curve | $-621.78 |
| equal_weight_hold | $449.75 |
| simple_trend | $-650.32 |

## 真实 L1 增量诊断

真实历史 IEX 报价与成交：9/11 训练残差，9/14 评估。9/14 下载了 1,726,959 条报价、69,599 条成交。IEX 是单交易所 L1，不能当作全市场 L2/L3。
同一 context_curve 模型、同一 $47,006.42、同一 5 bps 成交假设：无 L1 净亏 $1,084.65；加入 L1 净亏 $93.52，差额改善 $991.13。这不是账户真实盈利，也只有一天样本。

| 股票 | 有效训练桶 | 有效测试桶 | 无 L1 MSE (bps²) | 加 L1 MSE (bps²) |
|---|---:|---:|---:|---:|
| SNDK | 57 | 55 | 2029.07 | 2586.83 |
| TSLA | 73 | 76 | 461.05 | 500.75 |
| PLTR | 74 | 76 | 660.64 | 636.17 |
| NVDA | 76 | 76 | 210.38 | 169.24 |

SNDK、TSLA 的预测 MSE 没有改善；PLTR、NVDA 改善。组合单日亏损缩小不能替代多日逐股验证。缺少完整 L1 的桶明确退回量价基础模型。
历史 IEX 用交易所时间。实时采集用记录的 received_at 到达时间，两者不能混用。当前历史残差模型不会直接被实时运行器采用。
15:50–15:55 的实时到达数据诊断可生成 SNDK、TSLA、NVDA 的完整快照；PLTR 特征不全。诊断快照带 replay 标记，不能送入真实下单决策。
原始报价/成交文件保留在本机；公开研究包包含特征、来源哈希、模型、成交路径及结果。

## live_runner.py 的具体变更（待本次审阅后提交/推送）

完整逐行改动：[LIVE_RUNNER_DIRECTION_HOLDING_20260914.patch](LIVE_RUNNER_DIRECTION_HOLDING_20260914.patch)。

1. 按产物 kind 加载 HoldingModel / CalibratedHoldingModel；未配置新产物时仍加载现有 PolicyModel，默认路径不变。
2. 新模型加载股票与参考行情，保留所需历史，统一用已完成 K 线；参考 ETF 不产生订单。
3. 新模型输出目标权重进入原有 integer_targets → plan_rebalance → 券商提交/对账链，不另建假成交链。沿用账户上限和可借券检查。
4. 多期规划使用券商日历的真实收盘时间减现有平仓窗口；提前收市不会按 16:00 继续规划。
5. 可选 QUANT_L1_RESIDUAL_DIR 与 QUANT_L1_SNAPSHOT_PATH：仅接收已完成且及时到达的快照；校验源、feed、单位、时间语义、基础模型契约。缺失或不兼容则保留基础模型。
6. 仅将学习到的残差加到第一个五分钟预测，再重新求组合；对校准模型保留原始曲线，防止重复校准。
7. 状态接口新增真实决策诊断和成本假设标签。此前的收盘/盘后对账修复继续沿用。
8. 本次不自动扩大股数、不承诺固定胜率、不将历史最高候选换成线上模型。

## 使用与复现

在本地分支 feat/direction-holding-alpha-20260914 的仓库根目录执行。默认交易模型保持不变；先读 Lab 新增的三个实验选项。
```bash
python3 scripts/research_direction_holding.py --bars reports/holding_lab_20260914/bars --output /tmp/quant-holding-original
python3 scripts/research_direction_holding.py --bars reports/holding_lab_20260914/bars --output /tmp/quant-holding-calibrated --calibrated-only
python3 scripts/research_direction_holding.py --bars reports/holding_lab_20260914/bars --output /tmp/quant-holding-cost5 --calibrated-only --candidate calibrated_legacy_curve --policy-cost-bps 5
python3 scripts/capture_alpaca_l1.py --symbols SNDK TSLA PLTR NVDA --feed iex
python3 scripts/build_holding_l1_snapshot.py --input /path/to/capture --output /path/to/private/live_snapshot.json
```

快照命令需要在每根五分钟完成后重复运行，并与原采集器共享真实留存目录。当前未配置为云端自动任务；as-of 参数只供历史到达时间诊断。快照完成后才标记 available_at，过时快照不会进入决策。
真实到达时间训练尚需连续会话：用 prior-only 基础预测和成熟收益标签调用 HoldingL1Residual.fit，并传入 base_model_contract(model)。历史交易所时间模型不兼容，不可通过改标签绕过。
新量价模型产物在 reports/holding_lab_20260914/models/。这些是下一交易日研究候选，不是经过未来模拟证明的策略；QUANT_POLICY_PATH 仍指向旧产物。
现有 PaperForecast 同时支持 Ridge、Tree、LightGBM，但本次下单路径候选只评估 Ridge；没有声称三个模型全部参与当前订单。

## 验证与限制

已完成主回归 105 项检查、额外快照/接入检查及前端构建；最后修改的方向/日历/接入测试另行复跑。所有三个 Lab 包均通过数据哈希、产物哈希、毛净收益及逐股归因核对。
未来连续 Paper 验证、实时 L1 残差的多日训练与验证、官方费用结算对账仍未完成，不能用历史回放替代。
原 UI/UX、README、历史实验保留；只新增 Lab 选项、持仓指标及准确成本说明。没有本次新增 Git 提交或推送。
本地研究过程中 iCloud 再次将旧 Git index 变成 dataless 占位，导致 git bus error。已从相同 b34c5ad 提交恢复私有本地 Git 元数据，代码与实验均保留；原 Desktop 工作区不被覆盖。
本次是否推送接入代码，应审阅上述具体逻辑。收益证据尚不支持启用新候选或放大仓位。
