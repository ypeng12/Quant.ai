# Alpha 候选库交付

原 Desktop 工作区的 dataless 云端占位文件读取为空或超时，未覆盖这些文件。
完整可运行副本：`/Users/yuliangpeng/Quant-alpha-work`，分支 `feat/paper-alpha-library`，提交 `82cbc4ee67f2538e4d1659456353a8260c1d4841`。

完整实现说明：[/Users/yuliangpeng/Quant-alpha-work/docs/PAPER_ALPHA_LIBRARY.md](/Users/yuliangpeng/Quant-alpha-work/docs/PAPER_ALPHA_LIBRARY.md)。
构建产物：`/Users/yuliangpeng/Quant-alpha-work/reports/paper_alpha_library_20260913`。

源码补丁 `paper_alpha_source.patch` 基于 efa2997，包含源代码、测试、文档和 Lab 接入；不包含生成的 parquet / 模型产物。
原目录恢复正常读取后，可先运行 `git apply --check reports/paper_alpha_delivery_20260913/paper_alpha_source.patch` 检查再应用；完整产物已在独立副本及研究分支中保留。

20 只股票 + 3 个参考 ETF，31 列量价/截面输入，240 个已训练待验证模型。真实 L1 未提供留存数据，未训练或生成模拟盘口。28 项测试和前端构建通过。此轮没有策略盈利结论，live_runner 继续使用原有模型。
