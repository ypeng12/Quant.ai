# Quant AI 执行路径只读审计（2026-09-12）

## 做了什么

审阅 `live_runner.py`、`probability_engine.py`、`risk_position_sizer.py`、broker adapter、行情和缓存代码，核对 `runner_config.json` 及本地模型文件存在性。未导入或实例化 LiveTradingRunner，未访问 broker，未读取密钥，未提交订单。下面是代码层确定问题；其对最近每笔亏损的具体贡献仍需真实成交和当时信号回放归因。

更新：主任务随后授权修正缓存成功读取、零股风险预算和强制一股覆盖问题；这些确定数学/数据问题已局部修复，见“修改了什么”。下表中代码行号和复现输入保留审计前证据，其他 live / ML 问题仍是待处理项。

当前执行链为 `_run_loop` → `fetch_and_prepare_data` → `_build_intraday_opportunity` → `_evaluate_aggressive_intraday` → 仓位计算 → `submit_market_order`。`live_runner.py` 未直接调用 Lab / unified strategy / autonomous tracking pipeline。RL 加载和每日更新存在，但初始入场和普通持仓决策没有调用 RL policy。

### 优先处理的确定问题

| 问题 | 精确代码证据 | 实际含义 |
| --- | --- | --- |
| 日志展示初始止损，但执行路径没有落实 | `backend/app/broker/live_runner.py:785` 计算 `_stop_pct`，`:927` 保存，`:2379` 展示；持仓决策 `:1078` 至 `:1277` 没有初始止损比较；`backend/app/broker/alpaca_adapter.py:143` 至 `:153` 只提交 DAY 市价单，无 stop/bracket | `_stop_pct` 仅参与仓位计算，不是实际出场条件。此前未有足够浮盈启动 trailing、LOB 未满足反转时，亏损仓位可继续持有。不能把日志中的 Stop Loss 当作真实执行保证。 |
| 负期望、低胜率仍按方向开仓 | `live_runner.py:1023` 至 `:1076`，通过已有方向/影线/仓数等规则后直接 BUY/SHORT；`:2067` 至 `:2074` 仅用概率/收益预测排序；`:2363` 至 `:2381` 直接配股下单 | 不是 ML 在做正收益机会选择。`entry_score_min=78` 没有成为 active 决策参数；`is_positive_ev` 对初始入场不生效。 |
| 多空共用单个做多目标分类器 | `probability_engine.py:90` 对每 ticker 统一读取 `win_rate_model_{ticker}.joblib`，不区分 direction；`live_runner.py:800` 至 `:818` 同一输入同时拿两个模型正类概率；训练 `backend/data/train_per_ticker_models.py:117` 至 `:122` 目标为 `target_long_win` | 本地四个 per-ticker 文件均存在。只要加载成功，所谓 dedicated short 也是 long 模型，不能把此结果称为空头获胜概率。也不能简单用 `1-p_long` 代替，因为标签失败包括超时和震荡，未必等于空头获胜。 |
| 训练与执行时间尺度、特征含义不一致 | `train_per_ticker_models.py:60` 训练用 1 分钟 bars；`:104`、`:105` 分别用 5/15 根收益。当前 `runner_config.json` 为 `bar_interval=5m`，`live_runner.py:676`、`:677` 用 3/10 根，`:811`、`:812` 送入 5m/15m 特征 | 执行实际上把 15 分钟收益当成 5 分钟收益，把 50 分钟收益当成 15 分钟收益。EMA、ATR、RVOL 也从 1 分钟窗口变为 5 分钟窗口；修一处字段名无法解决整体分布错配。 |
| 缓存命中函数没有成功返回 | `backend/app/data_cache.py:35` 至 `:53` 检查文件/TTL 后函数结束，没有 `read_parquet` 或成功 return；`data_manager.py:210` 至 `:224` | 每次正常缓存读取都返回 None，重复请求 Yahoo。请求失败却读忽略 TTL 的旧缓存，且 live 没有 bar 时间戳/完成状态检查。可触发限流和旧信号交易；不应把注释中的 5m 缓存 TTL=2分钟当作实际缓存生效。 |
| 仓位零额度被覆盖为至少一股 | `risk_position_sizer.py:146` 至 `:152`：零股风险结果被忽略（只在 `vol_parity_shares > 0` 才限制），高价股又在 BP 达股价 90% 时强制一股 | 会突破当前账户和仓位预算。独立复现：equity=$1000、BP=$950、price=$1000 得到 1 股/$1000。不是增加新限制的需求，而是返回股数应符合现有配置表达的预算。 |
| 金字塔加仓绕过已有风险预算 | `risk_position_sizer.py:215` 至 `:219` 使用 `starter_buying_power_pct`，当前值 0.60；`live_runner.py:2268`、`:2303` 调用 | 直接使用剩余 BP 的 60%，无总持仓风险、已持有名义金额、现有 stop 风险计算；与初始入场 sizing 不同。“先卖半仓锁利润”后可能通过此路径重新显著放大敞口。 |

### 其他 active 逻辑错误与误导

1. **空头账本丢失成本队列**：`live_runner.py:360` 至 `:376` 在没有 long 库存的 SELL/SHORT 分支只将 action 改为 SHORT，没有 `short_q.append`。后续 COVER 在 `:340` 至 `:359` 会变成 BUY，正常做空盈亏无法正确配对。`TIER2_ADD_BUY` / `TIER2_ADD_SHORT` / `PYRAMID_SHORT` 也不在 FIFO action 分支。FIFO 又在 `:324`、`:325` 每天重置，不保留跨日成本。应以 broker fill 的 side/qty/price 重新归账，不能直接相信现有 `pnl` 和胜率。

2. **补仓和反转条件读不到输入**：`live_runner.py:885` 至 `:949` 的 opp 没有 `lower_wick_ratio`、`rsi`、`_open`；RSI 存为 `_rsi`。`:1049` 下影线空头拦截永远按 0 处理；`:1223` 至 `:1226` 的多头深跌补仓三个支撑条件全是默认值（0、50、close>close），因而该分支实际永远不成立；`:1243` 至 `:1245` 的空头补仓只剩已传入的 upper_wick 条件，形成多空不对称。这是字段契约错误，不是参数不好。

3. **概率被方向无关的人为规则覆盖**：`probability_engine.py:281` 至 `:282` 遇上影线/Bull Trap 时无论 LONG/SHORT 均把概率压到最多 38%，连应受益的空头也受罚；`:287` 至 `:299` PULLBACK/FADE 的 OFI 奖惩也未按交易方向翻转。`:301` 强制截断 35%–88%，`:133` 不确定性固定 4%，`:250` 至 `:253` 重设先验赔率后没有重新验证校准。最终 UI 的“胜率”是混合启发分数，不能仅凭名称理解为实测校准概率。

4. **MFE/MAE 不是条件实际盈利/亏损**：`probability_engine.py:412` 至 `:429` 使用未来窗口最大有利/不利波动回归值构造 `p*MFE-(1-p)*MAE-0.04`，并把 RR 下限设为 1。即使回归准确，持仓的 partial、LOB exit、trailing 等实际成交收益与 extrema 不是同一个目标；short 也未按方向交换或独立预测。计算出的 Kelly 未用于 `risk_position_sizer`，仓位实际使用至少 60% 的 conviction 倍数 (`:113`)；预测 MFE>=1.5 又直接变成 100% conviction (`:114`、`:115`)。

5. **更多训练/推断特征错配**：`live_runner.py:875` 用 ATR/2 作 VWAP zscore 分母，而 `train_advanced_ml_ensemble.py:132`、`:133` 用30条偏离的标准差；live `:876` 的 EMA slope 是 EMA9/前一收盘价，训练 `:138` 是 EMA9 相比三条前 EMA9；live `:894` OFI slope 固定0，而训练 `:117` 使用三条差分；live `:878` ER 默认0.25，data_manager 不产出 er；同一 dedicated alpha 预测在 `:813` 又默认0.35；live `:879` 用当日高点作 Donchian，训练 `:153`、`:154` 是20条高点。live `:881`、`:883` 以当前墙钟构造特征，历史回放若不注入行情时钟也会错。

6. **已提交被当成已成交**：adapter `:154` 至 `:160` 的 success 仅代表请求被接受，会同时返回 filled_qty=0。live `:2141`、`:2142` 已经设置 partial_tp_done；`:2199` 至 `:2205` 已改 tier；`:2281` 至 `:2283` 已改 pyramid 状态；`:2094` 至 `:2107` 全平请求接受就删跟踪状态。后续撤单/拒绝/部分成交可使策略状态与 broker 持仓不符。实际损失影响需对应 order events 验证。

7. **部分止盈后剩余仓位受固定退出锁影响**：live `:2138` 为 partial 设置 exit lock；`:1901` 至 `:1903` 只有 ticker 全平才主动解除；risk sizer `:26` 至 `:33` TTL 为60秒；live `:2006` 至 `:2008` 在此期间拦截全平。即使半仓已经完全成交，剩余仓位的 breakeven/反转退出仍可能受这一未按订单状态释放的锁影响。应由订单生命周期完成来解除重复单保护。

8. **仓位读取异常的本地 fallback 不完整**：`live_runner.py:1910` 读取 `_last_known_positions_list`，全文件没有对该字段赋值；adapter 尚无缓存且读取失败时回退成空持仓。adapter `:107` 至 `:109` 对已有缓存的所有异常又无条件复用，未上报缓存年龄。可以错认持仓/重复提交或错过退出，发生性须查当日 API 日志。

9. **模拟/实盘参数作用域不完整**：`live_runner.py:978` 至 `:989` 的 `_aggressive_orders_allowed` 只在 `:1261` 金字塔判断调用。初始 entry 和 Tier2 路径没有检查 `paper_only_aggressive` / `allow_aggressive_live`。配置虽然是 true/false，不能据此认定这些路径只会用模拟资金。本次未读取 broker 凭据，不判断实际账户环境。

10. **交易日历/盘后委托不一致**：`live_runner.py:1768` 至 `:1773` 仅按工作日+9:30–16:00推断开市，未利用 adapter 已有 `get_clock`；不处理交易所假期和提前收市。`:2088` 至 `:2172` SELL/COVER/PARTIAL 分支没有 `is_open` 判断，盘后仍可提交 DAY 市价单。EOD close 注释保证16:00前平仓，但 `alpaca_adapter.py:234` 接受 close_all 后即返回成功，仅异常时才降级盘后限价；不能把提交成功等同于实际零隔夜库存。

### active / 不生效配置区分

- 当前四股的 `TICKER_WAVE_PROFILES` **trailing 参数有效**；`min_wave_bps`、`p_win_threshold` 只有定义，没有被交易判断读取。
- `entry_score_min`、`full_size_score`、`minimum_hold_minutes`、`max_hold_minutes`、`daily_loss_limit_pct` 在本文件是定义而非 active 执行依据。`min_expected_value_r` 能改 `is_positive_ev`，但该值不控制普通新开仓。
- `_entry_confirmed` 和开盘 zero-delay 只被写入，初始执行不读取；因此不是开盘实际多bar确认机制。
- 当前反向交易 `inverted_mode=false`，`:728` 至 `:749` 的整体反向方向分支未启用；不要将其称为本次当前实际亏损来源。bull/bear trap 后续单独翻方向仍 active。
- 现有 cooldown、max_concurrent_positions、单影线 veto、每轮一个新仓等逻辑确实 active；与仓库“禁止未经同意固定拦截”规则存在历史不一致。本审计未添加此类逻辑，也不建议以新的亏损停机、标的封锁或限制频次代替纠正计算/数据错误。

### 无连接隔离复现结果

用 Python AST 仅提取 `_evaluate_aggressive_intraday`、默认参数、数值辅助方法和 ticker profile 到临时类，不执行 live 模块 imports 或构造函数；quality symbol 查询用内存 stub。RiskPositionSizer 仅运行无网络数学方法：

| 输入 | 代码实际输出 |
| --- | --- |
| flat、LONG_TREND、P_win=35%、E[R]=-0.80、无影线/冷却/仓数冲突 | BUY |
| entry=$100、price=$90、100股、`_stop_pct=0.008`、tier2、无 LOB 反转 | HOLD（浮亏10%仍非初始止损退出） |
| equity=$1000、buying_power=$950、price=$1000、ATR=$300 | 1 股 / $1000 notional（超出 $950 BP） |

以上是合成输入的确定行为证明，不是上周历史收益测算，也不证明任何替代策略已获利。

诊断脚本：`reports/quant_audit_20260912/reproduce_live_findings.py`。脚本输出 `bug_reproduced=true` 表示仍有缺陷，不是 correctness test 通过。仓位修复后的结果保存在 `reports/quant_audit_20260912/live_diagnostic_after_sizing_fix.json`：不足 BP 的返回已为 0 股，其余两个 live 行为仍可复现。

### live_runner 可审阅的拟议修订（尚未实施）

这份清单区分可以明确写出的接口修复与仍须历史验证才能定案的策略选择。不会新增亏损停机、标的锁死、频次限制或任意策略门槛。

1. **恢复原始行情字段契约**：`_build_intraday_opportunity` 的 `opp` 中补全下面字段，保留原 `_rsi` 兼容旧调用方。该变化会激活原本永不成立的多头深跌补仓，必须把激活后的真实行为一起回放，而不能以“只是补字段”跳过策略审阅。

   ```python
   "lower_wick_ratio": lower_wick_ratio,
   "rsi": rsi,
   "_open": self._safe_float(row.get("Open"), close),
   ```

2. **落实已经存在的每仓止损语义**：用首笔真实 fill 的均价和开仓时 `_stop_pct` 持久化每仓止损价，long 为 `filled_avg_price * (1 - entry_stop_pct)`、short 为 `filled_avg_price * (1 + entry_stop_pct)`；对持仓检测应在补仓判断之前。触发只返回该仓 SELL/COVER，后续新机会不被亏损锁定。不引入新的百分比，也不每根 bar 任意放宽初始止损。真实 quote、fill partial 与加仓后的整体止损/风险必须由同一仓位状态管理；现有 trailing 保留其已配置含义。

3. **修正成交状态机**：在 `_run_loop` 的初始、Tier2、pyramid、partial、full exit 分支，`success` 只登记 `pending order_id / side / requested_qty`；`filled_qty` 增量进入后才更新 shares、均价、tier、partial 状态和 extrema。拒绝/撤单释放未成交预留，full exit 只有经确认剩余仓位为零才清除状态。重复单保护按订单完成/撤销释放，避免已成交 partial 的剩余仓位继续受60秒退出锁影响。

4. **模拟配置按全路径生效**：在所有会增加持仓的初始、Tier2、pyramid 订单提交处，统一遵守已有 `paper_only_aggressive` 与 `allow_aggressive_live` 的同一判断。数值和用户现有选择不改，解决当前只在 pyramid 生效的问题。

5. **账本按真实成交记账**：将 `recalculate_trade_pnls` 的“日期分组后重置队列”改为全时间序列的有符号库存账本；broker `side=buy/sell` 决定数量增减，先结算对侧库存，再将剩余数量放入新方向成本队列。显式覆盖普通、Tier2、pyramid 和 partial 意图，但不为了配对覆盖原 action；日级盈亏仅在配对结束后汇总。账本计算需独立模块和交易样例验证。

6. **时间、行情和特征唯一来源**：所有推断时间来自 bar 时间戳；每种模型使用其训练约定的频率、交易时段、VWAP定义、EMA/ATR窗口、ER和动量 horizon。live 移除自造8/24特征映射，直接调用训练/回放同一个 causal feature builder；尚未得到兼容模型前，不能只改成1分钟或把3/10 bars改名就宣称已解决。缓存/持仓读失败应保留最近一次真实状态和来源时间，不能用 `[]` 冒充已知空仓；应利用已有交易所时钟信息处理假期/提前收市。

7. **多空概率和期望决策需要回测定案**：取消同一个 long 文件冒充 short 的路由，训练并校准独立方向的可执行收益目标；实际收益目标包含目前 partial、trailing、退出和成本。初始入场、加仓、退出都对齐同一预期净收益/资金配置目标，避免现在按方向必下单又把负 E[R] 只写进日志。具体方向选择和仓位函数需以逐日前向验证结果定案，本审计不自行增加 `P_win>=某常数` 等门槛。

## 修改了什么

已局部修改 `backend/app/data_cache.py`：fresh 缓存返回实际 parquet，损坏文件作为 cache miss。新增 `backend/tests/test_data_cache.py` 覆盖 fresh、expired、损坏 parquet、损坏/缺失 metadata；保留已有 ignore-TTL fallback 的原语义。

已局部修改 `backend/app/broker/risk_position_sizer.py`：`vol_parity_shares=0` 不再被忽略；aggressive/probe 不再把依据既有预算计算出的 0 股覆盖为 1 股。没有修改任一预算比例或添加策略门槛。新增 `backend/tests/test_risk_position_sizer.py` 覆盖不足 BP、明确0风险、ATR额度不足1股和正常预算内仓位。金字塔架构未改。

新增本审计文档、AST诊断脚本及诊断 JSON。未修改 `live_runner.py`、策略配置、模型或账本；未 commit / push。

## 打算做什么

由主任务汇总真实成交归账、四股逐日时间向前回放和 alpha/ML 审计；优先统一训练/推断特征及多空标签、成交和订单状态、缓存与现有预算计算，再使用未参与选择的后续日期检验候选逻辑。任何上周挑出的最好参数都只能作为待验证候选，不能据一周最优结果宣称未来每天赚钱。
