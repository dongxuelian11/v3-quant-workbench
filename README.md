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

首次使用免费数据源，先在“股票池”保存证券代码，再到“数据”选择日期并手动更新。数据逐股保存，后台可取消；同一天重新运行相同的未完成批次，会复用已完成的股票。导入已有文件后，可单独点击“保存研究区间”，无需联网更新。

CSV / Parquet 的行情列为 `symbol,date,open,high,low,close,volume`；证券代码支持 `SH600000`、`sh.600000`、`600000.SH` 或六位代码，成交量单位为股。估值因子使用 `peTTM,pbMRQ`。若输入前复权价格，应一并提供 `factor=前复权价/原始价`，用于还原实际成交价和股数；缺少的字段会在数据说明中列出。

财务文件包含 `symbol,announcementDate,reportDate`，其中公告日期不可省略；对应因子字段为 `roeAvg,YOYNI,YOYRevenue,netProfitMargin,liabilityToAsset`。BaoStock 的 `code,pubDate,statDate` 列名也可直接导入。

因子页支持 Qlib 公式，例如 `$close/Ref($close,10)-1`。策略的 Python 编辑器提供 `pd`、行情表 `prices` 和按日期、证券索引的评分 `scores`；修改 `scores` 并保留索引即可，例如 `scores = -scores` 将排序方向反转。撮合、费用和持仓仍由 Qlib 处理。

结果页先看整体表现；因子实验可从汇总进入单因子的完整 IC、分组收益和换手图。交易与持仓表支持分页和证券/日期筛选，点击一行打开对应行情。CSV 导出第一张完整结果表，Excel 包含全部表，PDF 为指标、参数和表格预览报告；图表图片单独导出。

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
