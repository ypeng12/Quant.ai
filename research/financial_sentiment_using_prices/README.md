# Train_Financial_Sentinment_Analysis_Using_Prices

这是 Quant.ai 内的 Python 研究起点，研究“用后续价格反应作为文本标签，能否给现有量化系统提供增量信息”。目录保留正式题目中的 `Sentinment` 拼写。整体方向、里程碑与 A/B 设计以[项目主计划](../../docs/financial_sentiment_using_prices_plan.md)为准；本文只说明这个模块如何复现。

目前状态：**Not trained / Not evaluated**。已经实现既有真实审计数据的只读加载、字段说明、覆盖统计及探索标签复核；没有训练情绪模型，没有运行交易 A/B，也没有收益提升结论。

## 与课程模板的关系

本目录参考 [`umd_classes/class_project/project_template`](https://github.com/gpsaggese/umd_classes/tree/60df5bc966d6da403eb54ee059372edc5cf20099/class_project/project_template)，基于提交 `60df5bc966d6da403eb54ee059372edc5cf20099` 的文件职责与 API/example notebook 结构。已阅读[创建工具](https://github.com/gpsaggese/umd_classes/blob/60df5bc966d6da403eb54ee059372edc5cf20099/class_project/create_project.py)和[Docker 说明](https://github.com/gpsaggese/umd_classes/blob/60df5bc966d6da403eb54ee059372edc5cf20099/class_project/project_template/docker_scripts.README.md)。

这是**适配 Quant 布局的 starter**，没有运行官方 `create_project.py`。适配包括：使用项目内脚本和 Python 工具模块，去掉对课程仓库根目录及 `helpers_root` 的依赖；采用与已验证本地环境一致的 Python 3.11；镜像名全小写；Jupyter 保留 token，宿主端口仅绑定 `127.0.0.1`。课程 issue、项目标签及提交目录仍需在正式提交时按[课程规则](https://github.com/gpsaggese/umd_classes/blob/60df5bc966d6da403eb54ee059372edc5cf20099/class_project/README.md)整理，当前没有伪造 issue 编号或声称已经提交课程 PR。

## 文件职责

| 文件 | 作用 |
|---|---|
| `financial_sentiment.API.ipynb` / `.API.py` | 展示数据加载、字段定义和简短真实样本 |
| `financial_sentiment.example.ipynb` / `.example.py` | 展示覆盖、排除原因及价格标签独立重算 |
| `financial_sentiment_utils.py` | 可复用的只读加载和验证函数，业务逻辑集中在这里 |
| `Dockerfile` / `requirements.txt` | Python 3.11 与 notebook 依赖；没有训练模型或交易 SDK |
| `docker_build.sh` / `docker_bash.sh` / `docker_jupyter.sh` | 本地构建、容器命令及 Jupyter 入口 |
| `docker_name.sh` / `utils.sh` / `run_jupyter.sh` | 当前项目的镜像配置、挂载和启动逻辑 |

Notebook 与 `.py` 使用 Jupytext `ipynb,py:percent` 配对；后续编辑后可运行 `jupytext --sync financial_sentiment.API.ipynb`，example 同理。

## 数据与可复现范围

默认读取 `../../reports/market_impact_data_audit_20261007/`。也可以设置 `FINANCIAL_SENTIMENT_DATA_DIR` 为已有审计目录的绝对路径。模块不会联网补数据；目录缺失或文件不完整时直接报错，不能把缺失数据伪装为零条。

本地已有快照包括 187 篇新闻、120 条富途查询记录（118 个唯一帖子 ID）、7 个行情标的的 5 个交易日，以及 SEC 元数据。203 个“新闻×股票”候选中，90 个满足当前探索窗口条件，涉及 81 篇新闻；其余 113 个有明确排除原因。运行时这些数值由文件计算，不是硬编码的模型结果。

复核使用 `max(created_at, updated_at) + 60 秒` 后的首个 5 分钟边界作为假设入场点，60 分钟后退出，比较个股与 SPY 的开盘价收益；限制在同一交易日且结束不晚于 15:55。还检查候选配对、重复 bars、归档哈希与保存的统计。**这验证的是归档内部一致性，不证明新闻当时的真实可见版本、不代表独立事件、因果效应或扣成本收益。** 富途首次快照缺失的响应接收时间仍然留空。

原始新闻和帖子快照是本地数据，并未因创建课程模块而取得对外再发布许可。干净克隆默认不含这些原始文件；其他运行者需要取得相同授权数据或单独约定可公开的替代数据集。当前不以虚构样本代替它们。

## 先用现有本地 Python 验证

在 Quant 仓库根目录，使用已有 Python 3.11 或更新版本即可重算归档标签：

```bash
python3 research/financial_sentiment_using_prices/financial_sentiment_utils.py
```

工具模块只依赖 Python 3.11 标准库；notebook 展示使用 pandas（2.3.3），不假定原 Quant 根目录存在 `.venv`。可以使用已有相容环境，或者在本模块目录独立准备环境：

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python financial_sentiment.API.py
.venv/bin/python financial_sentiment.example.py
.venv/bin/python -m jupyterlab
```

数据包版本与此次验证使用的研究环境一致：pandas 2.3.3、numpy 2.4.6。Notebook 依赖给出版本范围，尚不是跨平台完整锁定。没有为了此 starter 安装 Docker；以上环境创建和安装是供后续使用的命令，不代表已在原 Quant 执行。

## Docker 与 Jupyter 命令

在本目录运行：

```bash
./docker_build.sh
./docker_bash.sh -lc 'python financial_sentiment_utils.py'
./docker_bash.sh -lc 'python financial_sentiment.API.py && python financial_sentiment.example.py'
./docker_jupyter.sh -p 8890
```

从 Jupyter 输出复制带 token 的地址，使用宿主端口 `8890`，例如 `http://127.0.0.1:8890/lab?token=...`。项目目录挂载到 `/workspace`，便于保存 notebook；审计数据独立挂载到 `/data/audit:ro`，不会挂载整个 Quant 仓库或继承交易服务。

本地验收已通过：两本 notebook 分别在新的 Python 内核中执行全部 4／5 个代码单元；归档复算得到 203 个候选、90 个有效探索标签，收益重算最大误差为 0；shell 语法检查通过。Notebook 提交文件仍保留空输出，原始文本不会随执行结果提交。

后续具备 Docker 后，还需验证镜像构建、容器内 Jupyter 访问，以及 `jupyter nbconvert --to notebook --execute financial_sentiment.example.ipynb --output /tmp/financial_sentiment.example.executed.ipynb`。**Docker 构建与容器内运行尚未验证**；本地 notebook 成功不替代容器验收。

## 下一步的边界

先建立持续、带真实接收时间的数据集，再实现情绪基线与价格标签模型，按时间切分验证；最后接入 Quant.ai 的相同资金 A/B 实验。这些属于后续工作，不会由当前的数据审计成功自动推出。
