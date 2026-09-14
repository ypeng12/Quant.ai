# 真实 L1 采集与研究

当前四股为 SNDK、TSLA、PLTR、NVDA；来源是免费 IEX 单一交易所的最优买卖报价与成交。它不是合并 NBBO，也不是 L2/L3 挂单队列。行情采集与研究代码不导入交易模块，不提交订单。

## 要收集多久

- 连接后即可确认认证和订阅；非交易时间可以没有任何事件。
- 第一个完整交易日检查覆盖、异常报文、延迟与断线，跑通特征和模型。
- 5～10个未来交易日用于观察采集稳定性；完整分钟覆盖不代表逐笔无损。
- 预测优势需要另行冻结未来样本并评估成本。可先规划20～60个交易日，但不存在保证Alpha成立的固定天数。

历史数据能立即用于开发，不能重建当时的实际到达延迟。历史IEX、历史SIP和实时IEX分别登记，模型不能跨来源静默使用。

## 持续采集

后台运行副本：`~/.local/share/quant-l1/runtime`。可读研究副本：`~/.local/share/quant-l1/research-work`。凭证从已有私有文件读取，不复制到源代码、服务配置或报告。

```bash
python3 scripts/manage_l1_capture.py install \
  --symbols SNDK TSLA PLTR NVDA --feed iex \
  --env-file /absolute/path/to/private/backend/.env
python3 scripts/manage_l1_capture.py status
python3 scripts/manage_l1_capture.py stop
```

若Desktop再次变成iCloud占位文件，可使用完整可读路径：

```bash
python3 ~/.local/share/quant-l1/research-work/scripts/manage_l1_capture.py status
```

install明确启用当前macOS用户的launch agent；已有任务不会被自动覆盖。stop移除该任务的自启动配置，保留行情文件。更新运行代码需要stop后重新install。用户登录后任务自动运行；Mac休眠、退出登录或断网仍会产生缺口，本工具不修改系统睡眠设置。

采集服务使用 `Standard` 调度并关闭低优先级 I/O，避免主动把行情采集归为后台低优先级工作；这不是实时调度或不断线保证。`install --prevent-sleep-ac` 可选地使用 `caffeinate -s`，仅在接通电源时随采集进程维持睡眠断言，默认关闭，不更改全局电源设置。状态工具分别核验服务进程和采集器进程，防止把旧状态文件误报成正在采集。

- 实时数据：`~/.local/share/quant-l1/data/live_iex/YYYY-MM-DD/SYMBOL.jsonl`
- 状态：同根目录 `capture_status.json`
- 会话与重连记录：同根目录 `sessions/*.jsonl`
- 异常源报文：当日 `quarantine/`
- 日志：`~/.local/share/quant-l1/logs/`
- 代码哈希、路径与服务配置：`~/.local/share/quant-l1/service.json`

subscribed表示收到订阅确认，waiting_for_events表示尚无事件。只有进程存活、订阅确认和新鲜事件同时成立，状态API才标记实时。计数明确区分本次运行与文件尾部窗口，页面布局不变。

实际运行使用有界队列和单独写入线程，按接收顺序批量写文件。队列满时接收回调让出执行权并等待空间，不静默丢弃事件；持续磁盘阻塞仍可能造成上游积压。状态增加 `observed_events`、`enqueued_events`、`flushed_events`、`pending_flush_events`、`unaccepted_observed_events`，区分看到、接受和写出的数据。`writer_queue_delay_ms` 使用本机单调时钟，能衡量内部等待，但不能衡量行情网络延迟。

停止时先结束接收，再有界等待已接受事件写完。存储错误或 drain 超时会标记不完整，并保留未完成计数；不能把失败退出当作成功保存。批量 flush 仅保证 Python 缓冲写到操作系统，不承诺断电时物理磁盘持久性。更新服务前保留运行源码快照，等旧进程退出后再启新进程，避免免费行情连接相互挤占。

## 时间与缺口的含义

`received_at` 是采集进程在 SDK 回调处观察事件的本机时间，不是经过硬件校准的网卡接收时间。`received_at - timestamp` 同时受本机时钟、行情时钟、网络和处理积压影响。负值必须保留；不能删除负值、截成零，或把它解释成负的网络延迟。

质量报告 schema v3 保留旧 `latency_ms_*` 字段名，但明确其语义是未校准时间差，增加负时间差数量、比例与 `clock_alignment_verified=false`。独立时间探测只输出时钟偏差证据，不更改原始行情或系统时间。跨来源训练前仍需检查时间契约。

```bash
python3 scripts/probe_l1_clock.py --output /absolute/new_clock_probe.json
```

探测在有界时间内比较三个公开 NTP 服务，报告 UTC 相对本机的偏移、往返时间和估计不确定性。正偏移表示本机较慢；当前偏移不能直接用于平移过去全部数据。网络不可用会明确报告未获得结果。

已发现的本机时钟偏差也影响跨时钟新鲜度判断：在本机时刻之前观察到的真实报价，其交易所时间仍可能比本机时刻更晚。现有研究接口对此可能返回不可用；这不等于证明报价伪造或模型泄漏。在进行秒级实时 L1 验证前，仍须完成与数据时段对应的时钟校准及契约验证，本次不会自动修正这一问题或上线 L1 交易。

断线或休眠后可用历史接口补报价与成交，补录必须保存在独立目录并标为 `alpaca_stock_historical`。它可恢复历史行情记录，不能补出当时的实时接收时间；原始实时文件中的缺口仍然是缺口。历史完整下载、完整分钟覆盖和逐笔无损是不同结论。

## 质量审计与研究

```bash
python3 scripts/audit_l1_capture.py \
  --input /absolute/capture_root --symbols SNDK TSLA PLTR NVDA \
  --output /absolute/new_quality_report

python3 scripts/research_real_l1.py \
  --input /absolute/quotes_root /absolute/trades_root \
  --symbols SNDK TSLA PLTR NVDA --sessions 2026-09-11 \
  --output /absolute/new_model_report
```

每次使用新报告目录以保留失败实验。sessions明确限定日期，不会默默抽样；全部留存数据需要相应内存。研究按常规交易时段和真实交易日历处理，报告记录采样范围。原始事件与来源清单留存，完整性校验失败或未完成下载不能冒充合格输入。

入口生成QI Logistic、状态转移Microprice、1秒/5秒/30秒/1分钟/5分钟OFI Ridge。价差状态从训练数据学习并冻结，保留显式tick状态选项。模型登记特征版本、来源、时钟、训练日期、参数与哈希；状态为trained_unvalidated或带原因的unavailable，始终performance_verified=false、selected_for_live=null。

QI输出是下次IEX中间价上移概率，OFI Ridge目标是未来IEX中间价收益，均不能解释为交易胜率或净利润。IEX报价可能很宽，Microprice模型能训练也不能证明它代表全市场可成交价格。历史结果不核实价差成本、实际滑点或被动挂单成交率。

当前模型尚未接入live_runner。接入前需冻结未来样本、比较量价基准和L1增量、纳入实际成交成本，并核对训练推断契约。

## 本次权限验证

已实际验证现有账户可认证实时IEX、订阅四股Quotes/Trades，并查询较旧的历史SIP报价。没有启用付费订阅。官方依据：[Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)、[市场数据计划](https://docs.alpaca.markets/us/docs/about-market-data-api)。实际接口响应优先于静态说明。
