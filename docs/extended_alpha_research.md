# Alpha 扩展实验的使用边界

本轮把可由已有免费数据验证的方向写进 `backend/app/research/strategy_extensions.py`，使用共同的 `ResearchRuntime` 生成预测与组合目标。`scripts/run_extended_research.py` 进行整股现金账本回放，`scripts/shadow_extended_research.py` 接收未来本地完成行情并记录同一逻辑的纸面决策。没有券商调用或订单提交。

## 理论与实际实现

| 方向 | 本次实现与验证 | 尚不能据此声称 |
|---|---|---|
| 动量、短期反转、波动、量能、隔夜缺口 | 原有量价特征，加时段、隔夜与同一时段相对量能；Ridge、浅树和 LightGBM 比较 | 指标数量等于有效 Alpha 数量 |
| 信号与预测周期 | 5/15/30/60 分钟前瞻可执行收益；缺失中间 K 线则标签无效；每日只用前一天及更早数据拟合 | 所有信号有固定半衰期，或持仓必须等于预测周期 |
| K 线形态 | 加入去除实体、上下影线、收盘位置的对照 | K 线形态必有用或必无用 |
| 股票池泛化 | 四股、24 股交易池、跨股票 pooled 模型；参考资产保留在输入中 | 当前挑选的股票池代表无生存偏差的历史全市场 |
| 动态股票池 | 09:35 首根已完成行情的缺口/相对量能排序，选八股 | 已实现 09:25 盘前催化剂扫描 |
| 行业与市场相对收益 | 过去 beta、参考资产残差和共同参考风险惩罚 | 官方历史行业归属、完全消除市场风险 |
| 相对价值 | NVDA/AMD、NVDA/TSM、MSTR/IBIT 的过去对冲比率与未来价差收益模型；两腿成本与风险 | 必然均值回归、可强制赎回的 NAV 套利、天然高 Sharpe |
| 真实 L1 | 现有采集、OFI 与微价格特征模块及权限探测保留，缺数据的实验明确不可评估 | OHLCV 能重建订单簿，或没有真实数据也能回测 L1 |
| 财报与指数事件 | 研究来源和数据准入要求登记；本轮不可评估 | 今天下载的修订/预期数据就是过去当时已知的信息 |
| 限价、TWAP、POV | 现有成本与成交归因；需要真实报价及订单响应后再比较 | 碰价必成交、必获返佣、把成本参数调低就是执行改善 |

配对的经典研究可见 [Gatev 等论文页面](https://www.nber.org/papers/w7032)。对本项目的应用属于待检验假设，并未复刻论文的长期样本。MSTR/IBIT 的区别见 [Strategy 对其证券的说明](https://www.strategy.com/notes)。OFI、限价成交和事件效应的原始来源详见 [LOB 与执行说明](lob_data_and_execution.md)。

实际运行 `scripts/probe_free_extended_data.py` 查询 NVDA、TSLA、MSTR 的免费 Yahoo 盘前五分钟数据：接口返回了行情行，但三者盘前正成交量行数均为 **0**，不能据此计算可信的盘前 RVOL。NVDA、TSLA 财报表也确实返回了数据；当前查询没有给出历史预期修订与当时可用时间，不能把它们当作已验证的 point-in-time PEAD 数据。原始响应和覆盖统计保留在 `reports/free_extended_probe_20260913/`。这不是认定所有免费来源都没有这些数据，而是本次实际接口探测的结果。

## 为什么依然有数字参数

风险厌恶、最大敞口、模型深度、预测周期和选股容量必须有具体定义才能复现。本轮把它们作为明示实验规格保留，沿用 $100,000、95% 总敞口、70% 单标的上限和 2/5 bps 成本，避免通过改资金或假设制造改善。它们不是普遍适用的机构标准。

预测值直接进入联合组合目标：预测收益减相关风险、换手成本及可选参考风险。没有新增固定指标否决、强制一股、亏损锁定、时间段开仓锁或手工“胜率”。15:55 日内平仓沿用原研究协议。

## 结果与选择

Lab 的“Alpha 扩展实验”读取 `reports/extended_research_20260913_final/registry.json`，完整校验来源、行情与账本后显示。中断的初次运行留在 `reports/extended_research_20260913`，不作为完整结果发布。第二次运行只缓存重复标签计算，没有按首次盈亏改变候选或参数；测试验证缓存前后协方差完全相同。两次 QP 数值失败随后用同一目标的 SLSQP 重试完成；最终包保留原失败和不同运行的来源版本，完成 54 次模拟。

完整表与逐日、逐股归因见 `reports/extended_report_20260913/REPORT.md`。前五日选择规则和全区间事后最高分别展示。后四日以前也研究过，因此不能称为未接触测试集。未来纸面登记与实时交易配置分离；`live_runner.py` 沿用原策略。

## 未来纸面记录

```bash
python3 scripts/shadow_extended_research.py register --bundle reports/extended_research_20260913_final --directory reports/extended_forward_NEW
python3 scripts/shadow_extended_research.py record --directory reports/extended_forward_NEW --bars PATH_TO_FRESH_BARS --account-snapshot PATH_TO_PAPER_SNAPSHOT
python3 scripts/shadow_extended_research.py verify --directory reports/extended_forward_NEW
```

纸面快照格式：`{"simulation": true, "timestamp": "带时区的当前时间", "equity": 100000, "shares": {"每个交易标的": 0}}`。股份需要与所选候选完整对应；资金示例不是实际账户余额。行情包含注册面板的全部参考资产、训练历史及新完成的同步行情。只保留决策和输入，`pnl` 为 null，未模拟或宣称真实成交。市场未来的行情与成交不能通过今天重跑历史得到。

本轮前五日规则选出的是等权基准。该基准在交易日 09:25–09:30 预先记录 09:30 开盘目标，起始纸面库存需符合日内平仓假设，不把开盘后的目标倒填为开盘成交。预测模型的记录仍使用新鲜已完成的五分钟行情。
