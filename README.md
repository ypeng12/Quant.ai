---
title: Quant AI - Autonomous Institutional Algorithmic Trading Platform
emoji: 🚀
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: true
license: mit
short_description: ML Quant Trading Platform with C++ OFI Engine
tags:
  - quant
  - trading
  - algorithmic-trading
  - machine-learning
  - finance
  - high-frequency-trading
---

# 🚀 Quant.ai: 全自主机构级高频量化交易系统与算法矩阵
### Autonomous Institutional Algorithmic Trading Platform & High-Frequency Alpha Engine

<div align="center">

[![Hugging Face Spaces](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Space%20Live%20Demo-blue?style=for-the-badge&logo=huggingface)](https://huggingface.co/spaces/Ypeng12/quant-ai)
[![Live LOB Terminal](https://img.shields.io/badge/%F0%9F%8C%90%20Live%20Terminal-LOB%20Wave%20Alpha-00c805?style=for-the-badge)](https://ypeng12-quant-ai.hf.space/charts/saggese_wave_visual_dashboard.html)
[![C++20 Engine](https://img.shields.io/badge/C++20-Low%20Latency%20Engine-00599C?style=for-the-badge&logo=c%2B%2B)](https://isocpp.org/)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](https://opensource.org/licenses/MIT)

**[🌐 在线即刻体验 (Hugging Face Space Live Demo)](https://huggingface.co/spaces/Ypeng12/quant-ai)** · 
**[🌊 LOB 订单流波浪研判终端直达](https://ypeng12-quant-ai.hf.space/charts/saggese_wave_visual_dashboard.html)** · 
**[📚 学术量化研究手册](docs/QUANT_RESEARCH_HANDBOOK.md)** · 
**[📜 策略演进历史全景](docs/STRATEGY_EVOLUTION_HISTORY.md)**

</div>

---

## 🌟 项目概览 (Executive Overview)

**Quant.ai** 是一个融合**C++20 超低延迟底层引擎**、**微观订单流（LOB）因果机器学习**以及**自省强化学习（RL）**的次世代全自主量化交易系统。

系统针对美股高波动资产（如 TSLA、NVDA、MSTR、SNDK 等）提供全天候连续多空双向交易能力，彻底摒弃任何人工硬编码消极限制，全流程由**连续概率定价**与**数学期望收益 $E[R]$** 驱动，在保证极速撮合性能的同时实现严苛的统计套利与风险控制。

```
                         ┌─────────────────────────────────────────┐
                         │   Alpaca SIP / IEX 实时交易所行情流    │
                         └───────────────────┬─────────────────────┘
                                             │ WebSocket / Ticks
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ⚡ C++20 超低延迟引擎 (Nano-Second Core Engine)                                                │
│ ├─ NASDAQ ITCH 5.0 二进制反序列化 ───────► L2/L3 限价订单簿撮合 (Microsecond Order Book)     │
│ ├─ 无锁单生产者单消费者队列 (Lock-Free SPSC RingBuffer) ──► Sub-50μs 共享内存 (POSIX SHM IPC)│
│ └─ SIMD AVX-2 向量化微观特征加速 (OFI / Microprice Drift 实时计算)                            │
└────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                             │ Zero-Copy IPC / Pybind11
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 🧠 Python 实时 AI 推理与决策调度中心 (Institutional ML & Decision Core)                       │
│ ├─ GP Saggese 订单簿因果波浪预测器 (15~30m Wave Alpha, Purged CV 72.07%)                       │
│ ├─ 多模型校准概率网络 (Calibrated LightGBM + MFE/MAE 动态回归边界)                            │
│ ├─ 隐马尔可夫市场状态路由 (HMM Regime Detection: 牛市主升 / 熊市瀑布 / 高波震荡)              │
│ └─ 盘后自适应强化学习归因自省 (Daily Auto-Reflection Engine 动态更新 Q-Table)                  │
└────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                             │ Active Execution
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 🚀 激进高收益多空执行矩阵 (Max-Profit Dynamic Execution)                                       │
│ ├─ 跨截面动量龙头集中分配 (60% Capital Leader Concentration, 如单日捕捉 MSTR +5.7% 主升浪)    │
│ ├─ 浮盈金字塔顺势加仓 (Dynamic Staged Pyramid 60% Golden Add 滚仓乘胜追击)                    │
│ └─ 智能微观路由 (Smart Order Routing - SOR 权衡被动挂单 Maker 与主动扫盘 Taker)                │
└────────────────────────────────────────────┬───────────────────────────────────────────────────┘
                                             │ HTTP & WebSockets
                                             ▼
┌────────────────────────────────────────────────────────────────────────────────────────────────┐
│ 🖥️ 下一代交互式可视化研判终端 (Next-Gen Visual Terminals)                                     │
│ ├─ 🌊 LOB 订单流微观结构波浪终端: 当天实时 5m 流式刷新 + 7 大微观因果副图 + 去噪拐点标记      │
│ ├─ 📈 Robinhood 风格 ML 预测 vs 真实轨迹对照器: 霓虹发光曲线直观呈现模型预测路径与未来外推    │
│ └─ 📊 机构级 React Web 大屏: 实时监控账户购买力、多空仓位、盈亏雷达与系统健康度               │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 💎 五大硬核系统能力 (Five Core Superpowers)

### 1. ⚡ C++20 纳秒级超低延迟架构 (Ultra-Low Latency Engine)
* **二进制协议极速解析**：完整支持 NASDAQ ITCH 5.0 逐笔市场数据与 OUCH 订单提交协议，以纯位运算和内存映射方式实现纳秒级反序列化。
* **高频限价订单簿 (LOB)**：在 `cpp_engine/` 中手写高度优化的买卖十档深度内存队列，支持价格档位快速插入、取消、修改与跨价位即时撮合。
* **无锁通信与跨进程共享内存**：通过单生产者单消费者（SPSC）无锁环形队列和 POSIX SHM IPC，将 C++ 底层计算出的微观特征以**低于 50 微秒**的极低延迟投递至 Python AI 决策层。
* **SIMD AVX-2 向量加速**：针对海量分钟线与 Tick 序列，采用向量化指令集并行计算移动方差、相关性矩阵及 OFI 特征。

### 2. 🧠 顶尖机构级微观因果机器学习 (Institutional Microstructure ML)
* **GP Saggese (Teza Capital) 订单簿微观波浪模型**：
  摒弃粗暴过拟合的黑盒深度网络，回归订单流底层因果学。直接提取 **7 大核心微观结构特征**：
  1. **OFI (Order Flow Imbalance)**: 买卖各档报单量增减驱动力；
  2. **Microprice Drift (bps)**: 挂单量加权微观价格漂移基点；
  3. **Queue Imbalance**: 盘口排队失衡比率，捕捉冰山大单阻力；
  4. **Sweep Velocity**: 激进大单扫盘速度与买卖吸收率；
  5. **Volume Acceleration**: 5 分钟成交量爆发加速度；
  6. **Wick Absorption Ratio**: K 线影线资金吞吐吸收比；
  7. **HRT Toxic Flow**: 逆向选择毒性流风险度量。
* **严格杜绝前瞻偏差 (Purged K-Fold Cross Validation with Embargo)**：
  严格遵循 Marcos Lopez de Prado 机构量化标准，实施 Purged 与 Embargo 样本隔离，样本外交叉验证准确率稳定达 **61.97% ~ 72.07%**。
* **多模型胜率校准网络 (Calibrated Probabilities & Dynamic Regressors)**：
  经 Platt 缩放校准的真实做多/做空胜率 $P_{\text{win}}$，搭配前瞻最大有利波幅（MFE）与最大不利波幅（MAE）回归器，精准预估每笔机会的数学期望值。

![Microstructure Wave Terminal](assets/lob_microstructure_wave_terminal.png)

### 3. 🔄 强化学习日终自省与自进化 (Self-Reflecting Reinforcement Learning)
* **盘后自动归因反思 (Daily Auto-Reflection Engine)**：
  每交易日收盘后自动遍历当日所有成交明细，自动构建**错误分类法（Mistake Taxonomy）**（如逆势抢反弹接飞刀、假突破追高、震荡期过度交易等）。
* **动态更新 Q-Table 策略门控 (`rl_trading_agent.joblib`)**：
  强化学习 Agent 根据日内反馈动态调节行动策略权重（`Q-Policy Gate`），无需任何人肉硬编码修改，模型在持续交易中自主进化适应最新市场风格。

### 4. 🚀 激进高收益多空执行与资金管理 (Max-Profit Pyramid & Execution)
* **全天候连续多空自主交易**：严禁任何人为主观强停交易的消极限制，只要胜率与期望收益达标，系统连续开单捕捉日内波段。
* **跨截面动量龙头集中分配 (Leader Concentration)**：
  系统盘中动态打分全市场标的，将 60% 的优势购买力迅速倾斜至当前动量最强的超级领头羊标的（例如捕捉单日大单边暴涨主升浪）。
* **浮盈阶梯式金字塔加仓 (Dynamic Staged Pyramid 60% Golden Add)**：
  当底仓浮盈确立主升结构后，自动触发二阶金字塔顺势加仓，最大化利用杠杆与资金利用率将暴利吃满。
* **智能订单路由 (Smart Order Routing - SOR)**：
  动态估算盘口深度被扫穿概率与滑点冲击，在被动挂单（Maker，赚取流动性）与激进扫单（Taker，确保吃单成交）之间取得最优平衡。

| 胜率校准曲线 | 蒙特卡洛 CVaR 分布 | SOR 被动挂单 vs 主动扫单 |
| :---: | :---: | :---: |
| ![Calibration](assets/probability_calibration_curve.png) | ![CVaR](assets/monte_carlo_cvar_distribution.png) | ![SOR](assets/sor_maker_vs_taker_comparison.png) |

### 5. 🖥️ 沉浸式下一代量化全景可视化终端 (Next-Gen Visual Terminals)
* **🌊 订单流微观结构波浪研判终端 ([在线体验](https://ypeng12-quant-ai.hf.space/charts/saggese_wave_visual_dashboard.html))**：
  * 支持美股多标的秒级无缝切换；
  * **🌟 TODAY 实时盘中流式更新**：每 8 秒自动增量轮询最新 5m K 线、微观价格漂移与 OFI 柱状图；
  * 去噪智能波浪防抖锁，清晰提示 `WAVE LONG` 与 `WAVE SHORT` 核心拐点。
* **📈 Robinhood 风格预测轨迹回放器**：
  * 霓虹高亮真实分时走势 vs 虚线发光 ML 预测轨迹；
  * 动态外推未来 15~30 分钟价格期望波浪曲线。
* **📊 全功能 React 机构级监控大屏 ([frontend/](frontend/))**：
  * 实时账户资产净值曲线、持仓盈亏比例、购买力雷达与实时执行日志流水。

![Desktop Terminal](assets/desktop_terminal.png)

---

## 📂 优雅清晰的工程目录结构 (Clean Architecture)

```bash
Quant.ai/
├── .github/          # GitHub Actions 自动化 CI/CD 与 Hugging Face 实时双向同步
├── assets/           # 机构大屏截图、微观结构因果图表与徽章
├── backend/          # FastAPI 异步后端服务、WebSocket 服务与机器学习算法库
│   ├── app/          # 核心系统 (Alpha 引擎、风控核、数据管理、实盘执行器)
│   │   ├── broker/   # Alpaca 官方交易所网关与实盘执行流水
│   │   ├── ml/       # 7 大因果 LOB 算法、概率校准、自省强化学习与实时波浪服务
│   │   └── ipc/      # POSIX 共享内存与无锁跨进程通信桥
│   └── data/         # 历史数据集缓存与图表生成中心
├── cpp_engine/       # C++20 超低延迟引擎核心 (ITCH/OUCH 解包、订单簿撮合与无锁队列)
├── cpp_quant_engine/ # C++ 编译生成的二进制拓展加速模块
├── docs/             # 📚 学术量化研究手册、经典论文库 (PDF)、设计原则与历史演进录
│   ├── papers/       # Cont-Stoikov OFI、Bouchaud-Potters、Almgren-Chriss 等经典论文
│   ├── QUANT_RESEARCH_HANDBOOK.md    # 核心量化算法数学公式推导与完整手册
│   └── STRATEGY_EVOLUTION_HISTORY.md # 7/31 至今系统多轮演进全景对话历史档案
├── frontend/         # React + Vite + TypeScript 机构级量化交互大屏
├── reports/          # 策略历史仿真审计报告与统计学检验档案
├── scripts/          # 🛠️ 12 个离线仿真回测、策略优化、图表生成与实验脚本集
├── tests/            # 自动化全量单元测试与回归测试套件
├── Dockerfile        # 生产级多阶段容器化构建镜像
├── Makefile          # 自动化构建与测试一键指令
├── requirements.txt  # Python 核心依赖清单
└── README.md         # 项目全局中英双语总览
```

---

## 🛠️ 极速上手指南 (Quick Start)

### 1. 克隆仓库与安装依赖
```bash
git clone https://github.com/ypeng12/Quant.ai.git
cd Quant.ai

# 安装 Python 3.11 核心依赖
pip install -r requirements.txt
```

### 2. 编译 C++ 超低延迟引擎 (可选/生产就绪)
```bash
cd cpp_engine
mkdir build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j4
cd ../..
```

### 3. 一键启动本地量化 API 服务与可视化看板
```bash
# 启动 FastAPI 后端与实时微观计算服务 (监听 8000 端口)
python3 -m uvicorn backend.main_api:app --host 127.0.0.1 --port 8000 --reload
```
启动后在浏览器中打开：
* 🌊 **LOB 实时微观波浪研判终端**：[http://127.0.0.1:8000/saggese_wave_visual_dashboard.html](http://127.0.0.1:8000/saggese_wave_visual_dashboard.html)
* 📈 **交互式 API 文档 (Swagger)**：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 4. 运行离线策略仿真与训练脚本
```bash
# 运行全套后端测试
make test

# 运行最大化利润量化策略仿真评测
python3 scripts/run_max_profit_simulation.py --capital 500000

# 运行日终自动反思与强化学习训练
python3 scripts/run_daily_reflection.py --date 2026-09-11

# 重新生成全标的 LOB 微观结构波浪看板数据
python3 scripts/generate_saggese_wave_dashboard.py
```

---

## 📚 核心理论与文献基础 (Academic Foundations)

本平台核心算法严格植根于世界顶尖高频与量化金融学术文献：
1. **Cont, Kukanov & Stoikov (2014)**: *The Price Impact of Order Book Events* (订单流不平衡 OFI 理论基石)；
2. **Giacinto Paolo (GP) Saggese (Teza Capital / UMD)**: *Simple First & Interpretable Tree Models on Limit Order Book Dynamics*；
3. **Almgren & Chriss (2000)**: *Optimal Execution of Portfolio Transactions* (动态市场冲击与智能路由 SOR)；
4. **Marcos Lopez de Prado (2018)**: *Advances in Financial Machine Learning* (Purged K-Fold 交叉验证与 Deflated Sharpe Ratio 真实性审计)；
5. **Ledoit & Wolf (2004)**: *Honey, I Shrunk the Sample Covariance Matrix* (高维协方差压缩与风险平价)。

详细数学推导、协方差压缩公式及回测审计代码请参阅 **[docs/QUANT_RESEARCH_HANDBOOK.md](docs/QUANT_RESEARCH_HANDBOOK.md)**。

---

## ⚖️ 免责声明 (Disclaimer)

*本仓库仅供量化金融研究、学术探讨与算法工程交流使用。股市有风险，实盘交易涉及真实资金损益。使用者在运用本系统模型或策略进行实盘决策前，需充分理解高频交易市场风险并自行承担全部交易盈亏责任。*
