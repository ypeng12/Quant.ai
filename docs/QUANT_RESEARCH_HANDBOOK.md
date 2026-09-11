# 📚 Quant.ai 综合量化研究与系统架构手册 (Quant Research Handbook)

本文档将项目早期分散的所有研究报告（包含 `idea.md`、`ml.md`、`deep-research-report.md`、`ml_stock_assistant_blueprint.md`、`newreportml.md` 等）高精缩合并为**单一核心研究手册**，便于阅读与归档。

---

## 📖 目录
1. [小账户生存模式与风控框架 (原 idea.md)](#1-小账户生存模式与风控框架)
2. [概率化期望收益与 HMM 状态分类 (原 ml.md)](#2-概率化期望收益与-hmm-状态分类)
3. [HRT 风格 Algorithm Developer 实施蓝图 (原 deep-research-report.md)](#3-hrt-风格-algorithm-developer-实施蓝图)
4. [点位时间一致性与流动性门槛 (原 ml_stock_assistant_blueprint.md)](#4-点位时间一致性与流动性门槛)
5. [C++ 低延迟网络与无锁队列架构 (原 network_optimizations.md)](#5-c-低延迟网络与无锁队列架构)

---

## 1. 小账户生存模式与风控框架
- **核心理念**：对于 $800 ~ $50,000 规模的账户，第一原则不是追求高频暴利，而是把试错成本转移到回测与模拟端，把实盘错误限制在极小范围。
- **Deflated Sharpe Ratio (DSR)**：利用 Bailey & López de Prado 的 DSR 算法防范回测过拟合与选择性偏差。
- **动态风险控制**：规定单笔交易最大风险暴露不超过账户净资产的 $2.0\%$，并建立全账户 **单日 -1.0% 总熔断防线**。

---

## 2. 概率化期望收益与 HMM 状态分类
- **期望收益建模**：废除单一确定性技术指标打分，采用概率期望收益公式 $\text{EV} = \sum(\text{Return}_i \times \text{Prob}_i)$ 进行选股与排序。
- **隐马尔可夫模型 (HMM)**：将市场结构划分为 `TREND_BULL`（牛市趋势）、`RANGE_SIDEWAYS`（横盘震荡）、`VOLATILE_REVERSAL`（高波反转）。
- **实战效果**：在 `RANGE_SIDEWAYS` 震荡期强制 **100% 空仓保本 (CASH)**，避开无序拉锯与滑点磨损。

---

## 3. HRT 风格 Algorithm Developer 实施蓝图
- **点位时间一致性**：特征提取使用收盘后点位时间数据，交易指令在 `t+1` 开盘或首个 5 分钟 bar 执行，严格禁止未来函数 (No Lookahead)。
- **Purged & Embargoed Cross-Validation**：在时间序列验证中消除重叠标签带来的数据泄露。
- **C++20 低延迟引擎**：底层基于 C++20 编写 Order Flow Imbalance (OFI) 与 MicroPrice 漂移算法，原生导出 Pybind11 Python 模块。

---

## 4. 点位时间一致性与流动性门槛
- **流动性筛选**：自选股池限制为日均成交量 $\text{ADV}_{20} > 5\text{M}$ 美金且上市满 252 个交易日的高流动性标的，彻底杜绝低市值毛票（Penny Stocks）引发的爆雷。
- **单股硬熔断**：设置单股单日最大亏损限额 **`-$500`**，触发瞬间强行平仓并停止当日该股交易。

---

## 5. C++ 低延迟网络与无锁队列架构
- **SPSC RingBuffer 无锁队列**：多线程间行情与信号传递采用无锁环形缓冲区，避免互斥锁造成的上下文切换。
- **内存对齐与 `-O3` 编译**：利用 Cache Line 64字节对齐与 SIMD 指令集，将信号生成延迟压缩至微秒级（p99 $< 3.8\mu s$）。
