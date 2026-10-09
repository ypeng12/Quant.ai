# SIG 选举新闻采集说明

> 已归档：2026-10-09 用户要求移除 Election News。选举页面、选举 RSS 采集和自动 AI 摘要已停用；下文仅保留历史记录。

这份技术说明只对应 Quant.ai 的 **SIG Predictions Cup** 页面。该页只展示选举类新闻线索；目前尚未逐条匹配到 SIG 的具体市场，部分标题可能与本届题目无关。比赛策略与交易判断见 [SIG 比赛计划](PREDICTIONS_CUP_STRATEGY.md)。

## 当前目标

- 后端默认每 20 分钟采集 Google News 的“2026 美国中期选举”RSS、PBS NewsHour、ABC News 和 NBC News 的 Politics RSS，以及美国选举协助委员会（EAC）的 RSS。Google News 当前仅提供标题和来源；PBS、ABC、NBC 会提供长短不一的 RSS 摘录，NLP 只读取这些真实摘录。当前**没有接入 X**。SIG 页面每 60 秒读取本地索引，打开页面不会额外请求新闻网站。
- 保存标题、RSS 源提供的摘要/摘录（最多 1,600 字符）、原文链接、来源和发布时间；不抓取整篇网页。按链接和同日标题去重；关键词只决定阅读优先级，不代表事件概率。忽略超过 14 天的新闻，索引最多保留 5,000 条或 45 天。采集失败、最近成功时间均有记录。
- 有 RSS 摘录且标题达到优先级门槛时，后台最多每轮向 Gemini 发送 8 条新闻，每条只分析一次并缓存；重复轮询不重复花调用。只把标题、来源、时间和最多 1,600 字符的 RSS 摘录发给模型，不抓全文。Google 返回 429 后暂停 30 分钟。页面显示简短摘要、相关性、事件类型和人工核对重点；不计算概率、不匹配 SIG 合约、不提供交易指令。

## 配置与接口

| 配置 | 作用 |
| --- | --- |
| `QUANT_NEWS_POLL_SECONDS=1200` | 后台采集间隔，最短 300 秒。 |
| `QUANT_NEWS_DB_PATH=/persistent/path/news.sqlite3` | 指定 SQLite 缓存；默认在 Git 忽略的 `backend/.runtime_state/news.sqlite3`。无持久卷时，部署重启会丢失缓存。 |
| `SIG_GEMINI_API_KEY` | 后端可选 Gemini 密钥。本地密钥保存在 Git 忽略的 `backend/.runtime_state/sig_gemini_key`，文件权限为 `0600`；无密钥时照常收新闻，只不生成 NLP 摘要。 |
| `QUANT_NEWS_ENABLED=0` | 关闭共用后台采集线程；这不是 SIG 专用开关。 |

SIG 页面使用 `GET /api/news/items?topic=elections&limit=100`、`GET /api/news/sources` 和本地已缓存的 `GET /api/sig/triage` 结果。后端必须运行，页面才能显示信息。AI 调用统计按请求次数计；Google AI Studio 可查看该 Key 当前的模型额度与计费状态。

## 使用边界

RSS 摘录只是发现线索，不保证覆盖每场选举，也不一定包含完整报道。判断事件前应打开原始发布方，核实发布时间、完整内容及民调方法，再比对 SIG 的结算规则和可成交盘口。新增信息源时要检查访问方式、发布时间、使用许可与故障报告。
