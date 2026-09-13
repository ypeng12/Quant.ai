# 主流大市值股票：准入、预测和配仓

用户希望选择大公司、成交活跃的股票。实现文件为 `backend/app/research/liquid_policy.py`，由历史回放和 `scripts/shadow_liquid_policy.py` 共用。Lab 的「主流大市值股票 · 动态配仓」读取经过哈希、成本与盈亏恒等式校验的结果。

## 准入标准

- 前收盘价至少 $10，前 20 个完整交易日日均成交额至少 $50 million。只使用决策前的数据；盘中已完成 K 线价格以及模拟增加仓位的成交参考价也须达到价格标准。
- 当前市值至少 $50 billion。这是针对用户偏好的可配置研究门槛，不是行业统一规定，也不是公司经营成熟或股票安全的充分证明。
- 限已审核为 NYSE / Nasdaq 普通股或 ADR 的证券，排除 OTC、权证、ETF 和杠杆产品。参考 ETF 仅用于解释共同风险。
- 32 只候选股票和 10 只参考资产使用免费 Yahoo 五分钟行情。证券属性快照中 29 只股票达到市值标准，COIN、MARA、SMCI 未达到。SNDK、TSLA、MSTR、NVDA 均保留，未按已知回测盈亏排除 SNDK。
- 日均成交额是五分钟收盘价乘成交量的近似。完整交易日要求 78 根五分钟 K 线；短交易日或缺失数据会被明确标为数据不足，需要完整短日支持后才能扩大日期覆盖。

**历史范围限制：**市值与证券属性快照取得于 2026-09-13，没有历史逐时点市值与退市股票全集。此次结果只能说明“今天挑选的研究池在旧行情上的表现”，不能称为无选股偏差的全市场回测。未来模拟接口要求属性在交易日 09:25 前已知，并拒绝未来时间戳。股票池当前仍是明确列出的研究池，不是自动全市场扫描器。

## 每次如何决定资金

树模型与 Ridge 预测下一根可执行五分钟收益。每一天只用之前交易日训练；混合系数用前五天逐日向前验证的预测与真实标签拟合非负最小二乘，再在系数总和超过 1 时归一化，剩余权重相当于零收益先验。这个系数不是交易胜率，也没有承诺收益放大。

联合目标为预测收益减去风险惩罚和仓位变化成本。所有现有持仓均进入预算；不符合准入条件的旧持仓也计算平仓成本，不能从账户中凭空消失。候选包括：

1. 原四股树模型对照；
2. 同四股加准入条件；
3. 大市值股票每日开盘等权基准；
4. 大市值树模型；
5. 树与 Ridge 校准组合；
6. 校准组合加日内协方差更新、共同参考风险和预测残差风险；
7. 第六组加单股 25% 上限，作为单独的集中度偏好实验。

预测策略每根完整五分钟 K 线更新目标权重，下一根开盘按整数股模拟成交；没有固定优先买 MSTR 或平均分配四股。总目标敞口上限 95%，默认单股目标上限 70%，风险系数 50，单边成本 5 bps；这些继承对照条件以便比较，25% 上限另列。实际持仓会因价格跳空偏离目标上限。

共同参考风险使用过去数据估计的暴露与协方差，是偏保守的额外风险惩罚，可能与原协方差重复计入部分风险。预测残差协方差除以五个验证交易日只是近似不确定性尺度，并非统计上已经验证的置信区间。各组实验保留这些选择，避免将主观参数伪装成唯一正确的机构公式。

单边 5 bps 等于成交金额的 0.05%：买入 $10,000 扣 $5，卖出同样金额再扣 $5。它是合并的模拟摩擦假设，不是已核实的 Alpaca 收费。卖空可得性、借券费用、冲击、延迟和真实净值尚未对账。

## 运行与审查

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python3 scripts/run_liquid_research.py --output reports/liquid_research_NEW
python3 scripts/report_liquid_research.py --bundle reports/liquid_research_20260913_v2 --output reports/liquid_report_20260913
python3 scripts/shadow_liquid_policy.py register --bundle reports/liquid_research_NEW --directory reports/liquid_forward_NEW
python3 scripts/shadow_liquid_policy.py record --directory reports/liquid_forward_NEW --bars /path/to/fresh_42_asset_bars --instruments /path/to/current_instruments.json --account-snapshot /path/to/paper_account.json
python3 scripts/shadow_liquid_policy.py verify --directory reports/liquid_forward_NEW
```

输出目录必须不存在，以保留失败与成功尝试。首轮日历边界异常保存在 `reports/liquid_research_20260913`；修复周末边界后另建 v2。结果没有因为利润不理想而重写试验。

后续用户允许较小公司并希望更积极，因此当前源码另支持 `min_market_cap=0`（取消规模门槛，但仍须有有效正市值与证券属性）。大市值 v2 继续使用归档版本，注册其未来实验须按上面命令先复跑当前源码。新增积极配仓候选由 `active_policy.py` 和 `run_active_research.py` 单独记录，不重写 v2 的失败或亏损结果。

模拟账户 JSON 必须显式包含 `simulation: true`、带时区的 `timestamp`、正数 `equity`、全部候选股票的 `shares`（无仓位也写 0）。未知持仓不能忽略。行情保留足够的训练与 20 个完整交易日历史，并在所有股票和参考资产间同步。接口拒绝把历史 K 线记为新的未来验证。证券元数据原文写入决策哈希链，行情和账户快照保留内容哈希。

该接口只记录预测、目标仓位和原因，`orders_submitted=0`、`pnl=null`，不假设挂单成交或节省价差。真实未来模拟成交与净值仍需持续采集和对账。新逻辑已接入研究和模拟决策入口；`live_runner.py` 当前交易路径未切换。正式接入的审查范围是：用相同 `LiquidRuntime.prepare/target` 生成目标，提供完整当日股票池及账户持仓，保留券商证券权限与真实成交回执，再核对模型版本和资金预算。

## 研究依据与检验范围

联合优化预测收益、风险和交易成本可参考 [Boyd 等的多期凸优化交易框架](https://arxiv.org/abs/1705.00109)。估计误差和实际约束会显著改变配置，可参考 [AQR 的组合构建讨论](https://www.aqr.com/-/media/AQR/Documents/Insights/Alternative-Thinking/Alternative-Thinking-Strategic-Portfolio-Construction.pdf)。这些研究支持检验框架，不证明本项目任何候选能盈利。

本次沿用已经探索过的 2026-08-31 至 2026-09-11 九个交易日、$100,000 初始模拟资金、单边 5 bps。所有候选在同等条件下比较。不能把同一历史反复优化后的最好结果称为新的样本外收益；未来验证应从冻结代码后的真实观测开始。
