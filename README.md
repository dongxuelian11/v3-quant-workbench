# V3 量化研究工作台

面向 Windows 的 A 股日线量化研究软件。用项目组织数据、股票池、因子、策略、模型、回测与实验结果；通过中文 GUI 操作 Qlib、Alphalens、Optuna 等开源模块。

当前处于新版重构实现阶段。功能范围、进度和下一步统一记录在 [重构计划](docs/V3_REBUILD.md)。历史项目和实验文件保留，新版使用新的普通项目文件夹，需要的数据通过 CSV/Parquet 导入。

## 本地启动

需要 Node.js 24 和 Python 3.12。首次准备：

    npm ci
    npm run setup:research
    npm start

如果 Python 3.12 不在默认路径：

    npm run setup:research -- --python "C:/Python312/python.exe"

npm run dev 开启前端热更新。Python 运行时位于 runtime/research-python，与系统环境分开；桌面安装包包含解释器与依赖，使用者无需安装 Python。

## 使用流程

创建项目 → 获取或导入数据 → 配置股票池 → 批量分析因子 → 配置策略 → 回测 → 比较实验。

财务因子按公告日期进入研究。免费数据源的覆盖和历史修订能力以实际数据为准。模型按时间区间训练、验证和测试，寻优在验证区间进行。AI 的服务地址、模型和 API Key 在设置中填写；Ling-3.0-flash-Fin 可作为兼容服务候选，模型权重不随应用交付。

## 开发与交付

    npm run typecheck
    npm test
    npm run package:win

npm test 只运行新版研究功能的计算和持久化检查。普通修改选择相关检查，界面修改查看实际页面；整合和交付时再操作完整流程。CI 做一次编译和研究检查，安装包任务手动运行。

Windows 安装包输出在 artifacts/package。默认项目目录由用户选择，实验索引使用 SQLite，表格数据使用 Parquet，图表批注和布局随项目保存。

开发入口：apps/desktop/src/researchMain.ts、apps/desktop/src/renderer、apps/backend/src/v3_backend/research。GUI 和 AI 共用接口，定义见 packages/contracts/src/research.ts。

## 开源模块

Electron、React、Dockview、TanStack Table、Monaco、ECharts、KLineChart；Python 3.12、Qlib 0.9.7、alphalens-reloaded 0.4.6、BaoStock、AKShare、LightGBM、Ridge、Optuna、PydanticAI Slim。上游许可证随相应依赖保留。

本仓库使用 Apache-2.0 许可证。软件用于研究，不包含券商交易连接。
