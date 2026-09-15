# 9月14日 Alpha 后续审计

## 口径与复核
方向预测对齐下一根开盘至相应未来开盘；信号桶时间与可用时间相差5分钟。
逐行重算标签并与原始时间轴核对，缺失值排除，零收益按sign=0处理。分时段按信号桶归类。
原始历史IEX文件SHA256与原实验登记一致。逐桶重算QI、点差、报价数和成交方向失衡，均与产物一致。
30秒仅是现有成交报价对齐容忍时间和报告统计参照，不是新增交易限制；报价年龄不证明断线。
历史接口没有当时接收延迟，IEX不是全市场NBBO；本审计不能判定真实最优执行价或识别机构身份。

## 修正的方向匹配率
| model                                | period   |   bars |   valid |   excluded |   correct |   accuracy |
|:-------------------------------------|:---------|-------:|--------:|-----------:|----------:|-----------:|
| deployed_expected_5m_bps             | opening  |     12 |      12 |          0 |         6 |   0.5      |
| deployed_expected_5m_bps             | midday   |     42 |      42 |          0 |        17 |   0.404762 |
| deployed_expected_5m_bps             | closing  |     24 |      22 |          2 |        11 |   0.5      |
| calibrated_context_curve_cal_15m_bps | opening  |     12 |      12 |          0 |         7 |   0.583333 |
| calibrated_context_curve_cal_15m_bps | midday   |     42 |      42 |          0 |        23 |   0.547619 |
| calibrated_context_curve_cal_15m_bps | closing  |     24 |      20 |          4 |         8 |   0.4      |

## 原始L1质量
| symbol   |   quote_events |   zero_last_qi_bars |   missing_quote_bars |   last_quote_older_30s_bars |   median_last_quote_age_seconds |   max_last_quote_age_seconds |   missing_signed_trade_bars |   other_missing_feature_bars |   trade_count |   inside_spread_unclassified_trades |   no_prior_quote_within_30s_trades |   mean_bucket_median_spread_bps |
|:---------|---------------:|--------------------:|---------------------:|----------------------------:|--------------------------------:|-----------------------------:|----------------------------:|-----------------------------:|--------------:|------------------------------------:|-----------------------------------:|--------------------------------:|
| SNDK     |         164960 |                  67 |                    0 |                           0 |                       0.456821  |                    10.9966   |                          21 |                            0 |          9781 |                                9504 |                                  0 |                       227.283   |
| TSLA     |          74956 |                  28 |                    0 |                           0 |                       1.46545   |                    13.4806   |                           0 |                            0 |         13987 |                               12905 |                                  0 |                        43.282   |
| PLTR     |         316649 |                  47 |                    0 |                           0 |                       0.461634  |                     8.99725  |                           0 |                            0 |         13049 |                               11553 |                                  0 |                        14.0044  |
| NVDA     |        1170394 |                  44 |                    0 |                           0 |                       0.0650747 |                     0.926003 |                           0 |                            0 |         32782 |                               26356 |                                  0 |                         1.68624 |

零QI表示桶末最后有效报价两边数量相等。缺失signed trade不等于缺失报价；逐笔原因在trade_classification文件。
inside_spread_unclassified表示成交落在IEX买卖价之间，当前算法无法赋予方向，不能当作零净订单流。
SNDK的21个缺失桶均只缺signed_trade_imbalance，其他11列完整；对应全部21次原研究L1回退。
修复研究方向是按特征保留可用信息、显式加入成交分类覆盖率，并在过去训练数据上验证缺失处理；
不能把无法识别的成交强行标买或卖，也不能用0冒充已观测的平衡订单流。

## 实际模拟成交持仓归因
| strategy   | symbol   |   gross_pnl |   assumed_cost |   net_pnl |   fills |   turnover_dollars |   cash_reconciliation_error |
|:-----------|:---------|------------:|---------------:|----------:|--------:|-------------------:|----------------------------:|
| context    | TSLA     |     94.1556 |        29.3057 |   64.8499 |      16 |    58611.4         |                          -0 |
| context    | PLTR     |   -269.944  |       122.796  | -392.74   |      58 |   245592           |                          -0 |
| context    | NVDA     |   -257.77   |       143.771  | -401.541  |      57 |   287541           |                          -0 |
| context    | SNDK     |    215.849  |       108.194  |  107.655  |      42 |   216387           |                          -0 |
| hold       | SNDK     |    220.395  |        10.7609 |  209.634  |       2 |    21521.7         |                          -0 |
| hold       | TSLA     |    -16.7403 |        11.1501 |  -27.8903 |       2 |    22300.2         |                           0 |
| hold       | PLTR     |    257.4    |        11.1592 |  246.241  |       2 |    22318.4         |                          -0 |
| hold       | NVDA     |     32.7603 |        10.9925 |   21.7677 |       2 |    21985.1         |                          -0 |
| l1_base    | SNDK     |   -163.865  |       223.745  | -387.61   |      68 |   447490           |                          -0 |
| l1_base    | NVDA     |    -47.742  |       161.521  | -209.263  |      50 |   323043           |                          -0 |
| l1_base    | TSLA     |   -270.916  |       167.954  | -438.87   |      45 |   335908           |                          -0 |
| l1_base    | PLTR     |    153.522  |       202.432  |  -48.9098 |      65 |   404865           |                          -0 |
| l1_plus    | SNDK     |    145.553  |       602.956  | -457.403  |      73 |        1.20591e+06 |                          -0 |
| l1_plus    | PLTR     |    813.963  |       337.846  |  476.116  |      61 |   675693           |                          -0 |
| l1_plus    | NVDA     |    286.876  |       155.593  |  131.284  |      28 |   311185           |                          -0 |
| l1_plus    | TSLA     |     87.2528 |       330.769  | -243.517  |      47 |   661539           |                          -0 |

每两次成交间按上一笔成交后实际股数×参考价格变化计算毛利，再扣该笔已记录模拟成本。
所有路径尾仓为零；与成交现金流独立核对误差小于$0.000001。fill_price已含滑点，不重复扣除。
成本为原实验固定bps模拟摩擦，实际券商收费未验证。

### 加入L1的增量（plus减base）
| symbol   |   gross_pnl |   assumed_cost |   net_pnl |   fills |   turnover_dollars |
|:---------|------------:|---------------:|----------:|--------:|-------------------:|
| NVDA     |     334.618 |        -5.9287 |   340.547 |     -22 |           -11857.5 |
| PLTR     |     660.44  |       135.414  |   525.026 |      -4 |           270828   |
| SNDK     |     309.418 |       379.211  |   -69.793 |       5 |           758422   |
| TSLA     |     358.169 |       162.815  |   195.354 |       2 |           325631   |

这是两条整体策略路径的收益差，包含配仓和执行规模变化，不是隔离预测能力的因果实验。

### SNDK Context逐估值事件PF
{
  "sndk_positive_mark_pnl": 1359.7403564453125,
  "sndk_negative_mark_pnl": 1143.8912353515625,
  "mark_event_gross_profit_factor": 1.1886972418557007,
  "gross_pnl": 215.84912109375,
  "assumed_cost": 108.1937410888672,
  "net_pnl": 107.65538000488283,
  "interpretation": "Gross mark-event profit factor, not closed-trade PF or average win/loss ratio."
}

## 可用结论与边界
L1模型仅以9月11日一天训练；9月14日被反复研究，不能作为未触碰的验证集。
本次没有训练新模型、优化参数或修改下单链。先前“86%时间无盘口”“全天利润全在早盘”均不成立。
下一项策略实验应固定相同资金、成本与数据，对多期限预测、仓位平滑逐项比较；不能宣称已提高未来利润。

## 文件索引
- direction_rows.csv / direction_summary.csv：每条预测、可用时间、标签结束、匹配结果与有效样本数。
- *_quote_quality.csv：逐桶缺失字段、报价年龄、零QI及成交分类数量。
- *_trade_classification.csv：逐笔成交与前序报价匹配结果。
- filled_position_intervals.csv：实际模拟股数产生的持仓收益区间。
- context_hourly_attribution.csv：Context逐股、小时、方向归因。
- pnl_summary.csv / l1_incremental_attribution.csv：总盈亏与L1增量分解。
- registry.json：原始输入哈希和限制。重现命令：python3 scripts/audit_alpha_followup.py
