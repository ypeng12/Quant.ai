# 免费期权信息可用性审计 — 2026-09-15

**结论：本账户可读取 SNDK/TSLA 期权合约资料、indicative 最新快照以及较早的历史期权 K 线。可以据此建设延迟成交量与每日持仓量研究；尚不能把这些数据当作真实实时期权订单流，更没有证明它们提升股票策略收益。**

审计范围是给股票交易补充上下文，不涉及购买期权、订阅付费行情或改变账户设置。本次只发送 GET 请求，每只股票查询一个合约、一份快照、五根历史 K 线，未下载全链。

## 1. 本地实现核查

检查了 `backend`、`scripts`、`frontend/src` 中的 Python/TypeScript 源码。

- `backend/app/config.py:228` 有 `OPTIONS_QUANT_TRADER` 角色配置，包含 IV Rank、Skew、Delta/Gamma 等名称及固定权重。
- 当前未发现对应的 Alpaca 期权链/OI/OPRA 采集器，也未发现这些期权字段进入股票预测特征管道的实现。
- 因此“有期权策略角色配置”不等于“已经使用真实期权 Alpha”。这些配置数值是策略模板参数，不是来自市场的观察值。
- 本次保留所有现有界面及配置，仅增加审计文件与只读数据样本。

## 2. 官方数据口径

| 数据 | 已核实的官方含义 | 项目中的正确用法 |
|---|---|---|
| Indicative options feed | 免费衍生行情；报价经过修改，成交也是衍生数据并延迟15分钟 | 可用于接口联调；不能命名为真实实时期权盘口、扫单或机构买入 |
| OPRA feed | 期权市场合并最优买卖报价源；实时权限取决于订阅 | 仅在账户权限和数据来源核实后使用；本次未验证实时 OPRA 权限 |
| Historical option bars | 支持按合约、区间与周期查询；无实时权限时文档的默认截止时间为当前时间减15分钟 | 研究延迟可用的成交量、价格与合约活跃度；K线须完整闭合，并计入可获取延迟 |
| Option chain snapshot | 返回各合约最新成交、最新报价、Greeks等 | 是查询时快照，不是任意历史时点期权链；不能倒填昨天或今天早盘 |
| Open interest | 合约未平仓数量，并带有 `open_interest_date` | 是带日期的存量资料；不能视为当下新增买盘或盘中实时流量 |

来源：[Alpaca历史期权数据](https://docs.alpaca.markets/us/docs/historical-option-data)、[期权历史K线参数](https://docs.alpaca.markets/us/reference/optionbars)、[期权链快照](https://docs.alpaca.markets/us/reference/optionchain)、[OptionContract字段](https://alpaca.markets/sdks/python/api_reference/trading/models.html#optioncontract)。

Alpaca WebSocket 支持 `indicative` 与 `opra`，期权流采用 MsgPack；连接可用不改变 feed 本身的数据性质。[实时期权数据接口](https://docs.alpaca.markets/us/docs/real-time-option-data)

OCC需在日终清算配对后计算新的未平仓量。OI上升本身不能证明看涨，因为一份新增合约同时有买方和卖方。[OIC/OCC关于OI的解释](https://www.optionseducation.org/referencelibrary/faq/general-information)

## 3. 当前账户只读验证结果

查询时间：**2026-09-15 15:54:25 美东 / 19:54:25 UTC**。使用机器上已有的 Alpaca 配置；证据文件不保存密钥、请求认证头或账户标识。

| 项目 | SNDK样本 | TSLA样本 |
|---|---|---|
| 合约 | `SNDK260918C01500000` | `TSLA260918C00350000` |
| 到期日/类型 | 2026-09-18 / Call | 2026-09-18 / Call |
| 行权价 | $1,500 | $350 |
| 合约资料HTTP状态 | 200 | 200 |
| OI | 1,631 | 5,812 |
| **OI数据日期** | **2026-09-11** | **2026-09-11** |
| 最新 indicative 快照HTTP状态 | 200 | 200 |
| 历史5分钟K线HTTP状态 | 200 | 200 |
| 历史样本数 | 5，存在下一页 | 5，存在下一页 |
| 样本最新K线起点 | 2026-09-15 15:30 ET | 2026-09-15 15:30 ET |

两个合约按明确的到期、类型及行权区间取第一条，仅用于验证接口，不代表全链、最活跃合约或策略选择结果。

**实际核实到的OI甚至不是9月14日，而是9月11日。** 在9月15日查询时可见这个值，不足以证明该值在9月14日09:35已由项目接收到。`open_interest_date`是资料对应日期，不能代替发布时间和接收时间。

快照里的 `latestQuote` 接近查询时刻，`latestTrade` 分别约在15:37:53与15:39:19，符合延迟来源的特征。报价“时间新”不能消除 indicative 报价经过修改的性质。快照内 `dailyBar`、`minuteBar`、`prevDailyBar`、IV、Greeks保留原始返回值，但各字段的来源和更新周期未逐一独立验证。

历史K线请求使用官方 `/v1beta1/options/bars` 参数，未加入该端点文档未列出的 `feed` 参数。HTTP 200验证了本账户当前可取得这些较早的价格与成交量记录；响应没有显式 feed 字段，不据此宣称取得实时 OPRA 或完成全交易所逐笔核验。

原始市场数据及请求参数证据：[options_data_probe_20260915.json](../reports/options_data_probe_20260915.json)。这个文件只有两份合约样本，**不足以计算标的全链Put/Call比或Gamma敞口**。

## 4. 可以补充哪些股票交易特征

这些是待检验候选，先做数据采集和研究，再与原股票模型做同资金、同成本的对照。

| 候选 | 所需输入 | 时间与含义限制 |
|---|---|---|
| 延迟期权相对成交量 | 预先确定的合约池、已闭合历史bars、过去同时间段成交量 | 只使用真实可获取时刻之前的记录；不能将全日成交量用于上午预测 |
| 延迟Call/Put成交量比例 | 两边合约的完整采样口径、按到期和价内外程度分组 | 反映交易活动，不直接区分买入/卖出、开仓/平仓；单一Call合约无法计算 |
| 到期与行权价OI分布 | 每日保存的完整合约元数据和OI日期 | 是背景持仓集中度；不能把最大OI行权价当成必然支撑/压力 |
| 当日量/OI | 延迟累计成交量、最近实际可用OI及其日期 | OI较旧时显示资料年龄；分母缺失或零时该比值不可用 |
| IV期限结构/偏斜 | 同时点可靠报价、完整合约、明确估值方法 | 当前indicative IV仅记录为衍生快照；未获得可信历史快照前不用于回放早盘 |

免费情况下，近期最可执行的是**有延迟标注的期权成交量上下文**与**每日OI存档**。它们可与股价相对VWAP、当时已知支撑压力、成交量变化一起研究30/60分钟走势，不能用15分钟后才到的数据解释5分钟前已经发出的订单。

不从公开OI、总量或单笔大成交直接推断机构身份。Dealer Gamma的正负需要持仓方与买卖方向等假设，当前数据无法验证，不将“Gamma wall”或“主力扫单”作为实测事实。

## 5. 必须保存的数据时间及缺失信息

建议每条新记录保留 `provider`、`endpoint`、`requested_feed`、`response_feed_if_present`、`event_time`、`received_at`、`available_at`、`contract_symbol`、`expiration`、`strike`、`option_type`、`open_interest_date`、`coverage`、`quality_status`。

- 实时接收记录只能在 `received_at` 之后用于决策。
- 历史5分钟bar用开始时间标记时，最早可用时间先经过bar闭合，再加文档规定的延迟；真实采集还要考虑轮询/网络延迟。历史回填的到达时间属于假设，应单独标记。
- 最新快照不能回填旧时点的IV/Greeks/OI可见性。
- 未下载、未授权、过期、缺失、未定义分别保留状态；缺失不写成0，也不伪造正常的默认比率。
- 真实0成交量与缺失bar需要按数据源含义区分；不能仅因没有返回记录就声称没有成交。

## 6. 已完成与仍未知

已完成：官方文档核对、本地源码查找、两只股票小样本API验证及证据存档。

仍未知：实时OPRA是否授权、全链覆盖、各合约真实发布时间、历史OI快照、Greeks更新口径、延迟期权信息是否增加净收益。未启用任何期权驱动股票交易规则。

本报告为研究与工程可用性审计，不把9月14/15日走势或人工B/S截图作为已验证Alpha；账户费用也不从模拟滑点假设推定。
