# Quont.ai 简历项目描述模版 (Resume Project Description Template)

这里为您整理了适合写在简历上的项目描述。提供了 **中文版** 和 **英文版**，并针对 **量化开发岗 (Quant Developer)**、**算法交易工程师 (Algo Trading Engineer)** 与 **全栈/后端软件工程师 (Full-stack/Backend Engineer)** 进行了针对性的措辞优化。您可直接复制使用。

---

## 选项一：量化开发 / 量化研究 / 算法交易方向 (推荐优先使用)

### 中文版

**项目名称**：Quont.ai：高性能量化交易回测系统与交互式终端 (独立开发)  
**技术栈**：Python (FastAPI, Pandas, NumPy, yfinance) | React (TypeScript, Vite, Lightweight Charts) | Git  
**项目描述**：  
设计并开发了一款具备工业级风控管理与动态市场自适应的股票量化交易回测引擎及前端可视化终端，支持分钟级与日线级高频回测。

**核心工作与技术亮点**：
* **量化特征与形态工程**：利用 Pandas 与 NumPy 向量化计算，构建了 12 种 K 线数值特征与 22 种经典价格形态（包括 Hammer、Engulfing 以及基于颈线突破判定算法的 W底 / M顶检测器），实现毫秒级的大规模行情特征提取。
* **自适应市场状态路由器 (Market Regime Router)**：基于 Wilder's ADX (平均趋向指数) 以及 rolling 252日波动率分位数计算，设计了将市场分类为四种状态（trend_up, trend_down, high_volatility, range_bound）的判定路由。动态引导顺势突破（Donchian Channel/EMA）与均值回归（Bollinger Bands）子策略，在不利行情或高风险波动下自动执行空仓防御。
* **多层级资金管理与熔断风控系统**：实现了基于 ATR (真实波幅) 与账户动态权益的波动率头寸自适应算仓算法。设计了软回撤（7% 回撤触发仓位减半）、连续亏损（连续5笔触发仓位减半）与硬回撤（12% 回撤触发交易熔断，Multiplier 置 0）三层主动风险控制闸门。
* **样本外滚动参数优化引擎 (Walk-Forward Optimizer)**：开发了滚动优化回测框架，利用训练/测试窗口滑动校验，通过网格搜索动态寻找卡玛比率（Calmar Ratio，回撤惩罚后净收益）最高的参数组合，并进行样本外验证，显著降低了策略的过拟合风险。
* **高性能交互式终端**：基于 React 19 + TypeScript + Vite 搭建了流式数据看板，使用 TradingView 官方高性能图表（Lightweight Charts）实时渲染 K 线、波动率通道、形态标记与买卖点轨迹，适配全移动端响应式布局。

---

### 英文版 (English Version)

**Project Name**: Quont.ai: High-Performance Algorithmic Trading Engine & Backtest Simulator (Sole Developer)  
**Tech Stack**: Python (FastAPI, Pandas, NumPy, yfinance) | React (TypeScript, Vite, Lightweight Charts) | Git  
**Project Description**:  
Designed and developed a production-ready, fully-automated quantitative trading backtest engine and interactive visual dashboard, supporting high-fidelity historical simulations at both minute and daily intervals.

**Key Achievements & Engineering Highlights**:
* **Vectorized Feature & Pattern Engineering**: Implemented vectorized extraction of 12 candlestick numerical features and 22 quantifiable price patterns (e.g., Hammer, Engulfing, and complex neckline-breakout W-Bottoms/M-Tops) using Pandas and NumPy, achieving sub-millisecond calculation speeds.
* **Dynamic Market Regime Router**: Built a rule-based classification engine to divide market conditions into four regimes (`trend_up`, `trend_down`, `high_volatility`, `range_bound`) based on Wilder's ADX and rolling volatility quantiles. Router dynamically switches between trend-following (Donchian) and mean-reversion (Bollinger) sub-strategies, enforcing defensive cash holds during bearish or high-risk regimes.
* **Institutional-Grade Risk Control & Sizing**: Developed a volatility-adjusted position sizing algorithm based on Average True Range (ATR) and live portfolio equity. Implemented a multi-tier active risk control gate: a 7% equity drawdown or 5 consecutive losses triggers 50% position downsizing, while a 12% hard drawdown enforces a full trading melt-down (multiplier set to 0) to prevent catastrophic tail-risk.
* **Walk-Forward Rolling Parameter Optimizer**: Engineered a rolling optimization pipeline that splits historical sequences into train and test folds. Conducted parameter grid scans to maximize the drawdown-penalized return (Calmar ratio) and verified out-of-sample performance to mitigate lookahead bias and curve-fitting.
* **Responsive Visual Terminal**: Designed a mobile-responsive terminal with React 19 and TypeScript, integrating TradingView's Lightweight Charts to render candlestick bars, technical indicator envelopes, dynamic regime overlays, and precise trade execution markers.

---

## 选项二：全栈开发 / 后端开发方向 (推荐注重软件工程能力时使用)

### 中文版

**项目名称**：Quont.ai：量化交易模拟回测与数据终端 (独立开发)  
**技术栈**：Python (FastAPI, Pandas, NumPy) | React (TypeScript, Vite) | RESTful API | CORS  
**核心工作**：
* **模块化系统架构**：基于“低耦合、高内聚”原则，采用 FastAPI (后端) 与 Vite React (前端) 分离架构，搭建了模块化的策略回测与资产变动计算核心（包含数据管理器、双向交易账本、形态识别器、风控总线与参数优化器）。
* **高性能数值计算**：避免显式 Python 循环，使用 NumPy 与 Pandas 向量化处理股票行情数据，显著提升了高频数据（分钟级）的计算处理效率。
* **容错与健全性设计**：设计了针对 YFinance 网络延迟与空值率高的 API 容错层，开发了数值清洗中间件（`clean_float`），防止任何因 NaN 或 Inf 数据导致的 JSON 序列化 500 异常，保证了线上服务的 100% 稳定性。
* **高交互性 UI 开发**：利用 HTML5 与原声 CSS 媒体查询设计了高度响应式的 UI 框架。在移动端屏幕（如 390px 宽度）与桌面宽屏间无缝切换，实现图表自适应缩放与自选股组件重组。
