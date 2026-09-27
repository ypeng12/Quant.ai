# SIG 选举信息采集说明

这份技术说明只对应 Quant.ai 的 **SIG Predictions Cup** 页面。该页只展示选举类新闻线索；目前尚未逐条匹配到 SIG 的具体市场，部分标题可能与本届题目无关。比赛策略与交易判断见 [SIG 比赛计划](PREDICTIONS_CUP_STRATEGY.md)。

## 目前接入的信息

- 后端默认每 20 分钟采集一次 Google News 的“2026 美国中期选举”RSS，以及美国选举协助委员会（EAC）的 RSS。当前**没有接入 X**。SIG 页面每 60 秒读取本地索引，打开页面不会额外请求新闻网站。
- 只保存标题、原文链接、来源和发布时间，不下载文章全文。按链接和同日标题去重；关键词只决定阅读优先级，不代表事件概率。过期标题会清理，数据库最多保留 5,000 条索引或 45 天内的其他索引。采集失败、最近成功时间均有记录。
- 每轮最多用 Gemini 分析 8 条尚未分析的高优先级选举标题；其他标题可手动分析。模型只看到 RSS 元数据，输出相关性、事件类型、标题主张与可核对的原文片段。成功结果按新闻 ID 缓存。**模型不阅读正文、不预测胜率、不匹配 SIG 合约、不提供交易指令。**

## 配置与接口

| 配置 | 作用 |
| --- | --- |
| `QUANT_NEWS_POLL_SECONDS=1200` | 后台采集间隔，最短 300 秒。 |
| `QUANT_NEWS_DB_PATH=/persistent/path/news.sqlite3` | 指定 SQLite 缓存；默认在 Git 忽略的 `backend/.runtime_state/news.sqlite3`。无持久卷时，部署重启会丢失缓存。 |
| `SIG_GEMINI_API_KEY` | 在后端设置 Gemini 密钥。本地密钥保存在 Git 忽略的 `backend/.runtime_state/sig_gemini_key`，文件权限为 `0600`。 |
| `QUANT_NEWS_ENABLED=0` | 关闭共用后台采集线程；这不是 SIG 专用开关。 |

SIG 页面使用 `GET /api/news/items?topic=elections&limit=40`、`GET /api/news/sources` 和 `GET /api/sig/triage` 读取本地数据。手动分析调用 `POST /api/sig/triage/{news_id}`，会请求 Gemini。后端必须运行，页面才能显示信息。

模型从固定 Flash 名单中选择当前密钥可用的版本，优先 `gemini-3.5-flash`。按用户要求，没有本地每日调用上限；Google 返回 429 时，后台 AI 分析暂停 30 分钟，标题仍可浏览。密钥不会进入前端或代码仓库。**只凭密钥无法判断项目是否会计费**，实际套餐和限制需在 Google AI Studio 查看。

## 使用边界

Google News 标题只是发现线索，EAC RSS 也不保证覆盖每场选举。判断事件前应打开原始发布方，核实发布时间、完整内容及民调方法，再比对 SIG 的结算规则和可成交盘口。新增信息源时要检查访问方式、发布时间、使用许可与故障报告；GDELT 和部分民调网站 RSS 目前因访问错误未接入。
