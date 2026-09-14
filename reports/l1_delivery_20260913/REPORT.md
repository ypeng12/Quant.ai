# 真实 L1 交付报告（2026-09-13）

## 已完成

- 已用现有凭证实际验证历史SIP报价HTTP 200及免费IEX实时认证、四股Quotes/Trades订阅。未购买订阅、未提交股票订单。
- macOS后台采集已运行，标的SNDK、TSLA、PLTR、NVDA。当前为周日，实时事件为0，状态为已订阅等待开市。
- 2026-09-11常规交易时段：1,681,251条真实IEX报价、51,685条真实成交。所有股票的390分钟均有报价和成交；未发现重复、非法或交叉报价。覆盖不证明逐笔无损。
- 用同一完整交易日、不抽样，训练28份研究模型：每股QI Logistic、状态转移Microprice、1s/5s/30s/1min/5min OFI Ridge。28份均trained_unvalidated，未验证盈利，未选入live_runner。
- 55项相关测试通过；源文件、输入和模型哈希留存；SDK websockets.legacy有一项弃用提示。

## 数据与模型明细

| 股票 | 报价 | 成交 | IEX价差中位(bps) | 已训练待验证模型 |
|---|---:|---:|---:|---:|
| SNDK | 176,340 | 7,905 | 88.94 | 7 |
| TSLA | 96,234 | 12,661 | 31.00 | 7 |
| PLTR | 179,986 | 7,355 | 37.03 | 7 |
| NVDA | 1,228,691 | 23,764 | 1.81 | 7 |

IEX价差仅表示该交易所的报价，不是合并NBBO，也不是已经核实的交易成本。SNDK宽价差使旧1～5美分状态范围几乎没有支持数据；现改为仅在训练前缀学习分位数边界，推断冻结。能拟合并不等于能按这些价格成交或获利。

## 修改范围

保留UI、README和live_runner。修改采集和历史凭证读取、质量报告、状态接口的底层读取；新增研究模型、CLI和macOS服务管理。异常原报文留存，跨日/重连切断OFI与标签，迟到事件显式计数，历史与真实接收时钟分别登记。

Desktop的部分源文件出现iCloud占位，已保留非云端可读研究副本和运行快照。最终四股复现输入位于非云端目录；早期Desktop下载和失败实验保留。整批十日报价下载未全部完成，清单仍标为incomplete；SNDK、TSLA已完成的分区未冒充整个四股十日样本。

## 后续时间与使用

已经可以研究历史L1。未来首个完整交易日检查到达延迟和断线；5～10个未来交易日观察采集稳定性；预测优势需另外冻结未来样本并纳入成本，不存在保证Alpha成立的固定天数。Mac须保持唤醒、登录和联网，服务不会更改睡眠设置。

```bash
python3 ~/.local/share/quant-l1/research-work/scripts/manage_l1_capture.py status
python3 ~/.local/share/quant-l1/research-work/scripts/manage_l1_capture.py stop
```

模型登记：[models_20260911/registry.json](models_20260911/registry.json)；质量报告：[报价](quote_quality_20260911/summary.json)、[成交](trade_quality_20260911/summary.json)；验证：[validation.json](validation.json)。

原始实时数据：`~/.local/share/quant-l1/data/live_iex`；四股历史输入：`~/.local/share/quant-l1/data/history_iex_20260911_quotes`与`history_iex_20260911_trades`。

当前没有L1策略净利润、样本外胜率或资金分配结果；这些仍未验证。

官方数据权限依据：[Alpaca Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)。
