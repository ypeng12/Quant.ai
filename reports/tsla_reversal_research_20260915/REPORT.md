# TSLA反转策略开发对照

截至 2026-09-15T11:00:00-04:00，期初资金 $47958.07。未平仓按最后已完成K线收盘估值，未收盘，不是券商实现盈利。

| strategy                    | symbol   |   net_pnl |   gross_pnl |   assumed_cost |   fills |   ending_shares |   ending_mark |
|:----------------------------|:---------|----------:|------------:|---------------:|--------:|----------------:|--------------:|
| frozen_5m                   | SNDK     |      6.54 |       16.67 |          10.14 |       5 |               1 |       1542.76 |
| frozen_5m                   | TSLA     |   -985.96 |     -924.98 |          60.98 |       8 |              34 |        357.61 |
| frozen_5m                   | PLTR     |      0    |        0    |           0    |       0 |               0 |        170.84 |
| frozen_5m                   | NVDA     |     38.81 |       50.22 |          11.41 |       5 |             -49 |        212.04 |
| context_curve               | SNDK     |   -342.21 |     -301.69 |          40.52 |      16 |               0 |       1542.76 |
| context_curve               | TSLA     |   -718.64 |     -626.35 |          92.3  |      16 |               0 |        357.61 |
| context_curve               | PLTR     |      0    |        0    |           0    |       0 |               0 |        170.84 |
| context_curve               | NVDA     |     79.24 |       90.32 |          11.07 |       6 |             -98 |        212.04 |
| session_context_curve       | SNDK     |   -312.48 |     -264.92 |          47.56 |      16 |              -1 |       1542.76 |
| session_context_curve       | TSLA     |   -863.7  |     -727.64 |         136.07 |      18 |               5 |        357.61 |
| session_context_curve       | PLTR     |      0    |        0    |           0    |       0 |               0 |        170.84 |
| session_context_curve       | NVDA     |     50.73 |       56.27 |           5.54 |       5 |             -44 |        212.04 |
| session_context_error_curve | SNDK     |   -273.08 |     -233.31 |          39.78 |      15 |              -1 |       1542.76 |
| session_context_error_curve | TSLA     |   -732.66 |     -635.66 |          96.99 |      21 |               0 |        357.61 |
| session_context_error_curve | PLTR     |      0    |        0    |           0    |       0 |               0 |        170.84 |
| session_context_error_curve | NVDA     |     27.81 |       31.54 |           3.73 |       7 |             -23 |        212.04 |

新特征从当前及此前已完成K线计算；使用模型学习方向，不按今天走势写多空规则。误差风险仅用此前日期前向校准残差。

- Intraday marked simulation, not realized broker profit or a full-session result.
- Today was inspected before this change; it is development evidence, not an untouched holdout.
- Models trained before today; next-bar open assumed executable with full fills and configured friction.
- Forecast risk uses overlapping prior forward errors; not a confidence guarantee.
- All variants trade the same three online symbols. PLTR supplies peer features only; MSTR is input only for legacy parity.
- Yahoo snapshot matches runner provider but may differ from original live fetch; no exact historical decision log available.

决策明细：TSLA_decision_comparison.csv。训练产物为候选，未激活或发送订单。
