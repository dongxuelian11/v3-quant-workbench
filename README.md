# V3 量化研究工作台

面向 Windows 的 A 股日线量化研究软件。项目内可建立多份策略，共享数据，分别保存草稿、启用方案与实验；通过中文 GUI 操作 Qlib、Alphalens、Optuna 等开源模块。

功能范围、进度和下一步统一记录在 [重构计划](docs/V3_REBUILD.md)。旧项目继续打开并映射为默认策略，旧实验保持原样。新项目默认引用软件共享数据，也可继续使用已有项目的数据目录。

## 本地启动

需要 Node.js 24 和 Python 3.12。首次准备：

    npm ci
    npm run setup:research
    npm start

如果 Python 3.12 不在默认路径：

    npm run setup:research -- --python "C:/Python312/python.exe"

npm run dev 开启前端热更新。Python 运行时位于 runtime/research-python，与系统环境分开；桌面安装包包含解释器与依赖，使用者无需安装 Python。

## 使用流程

从“今日工作台”继续研究，或直接打开市场概况、筛选、自选、实际持仓和数据中心。研究流程为：创建项目与策略 → 获取或导入数据 → 配置股票池 → 分析因子 → 编辑策略 → 回测 → 比较实验。

策略首先展示配置摘要和近期实验；“编辑参数”展开控件，修改自动保存为草稿。运行产生独立实验，“应用到每日选股”才更新启用方案。股票、策略和实验各自作为标签打开，可拖动分屏或移到独立 Windows 窗口；自定义布局、窗口位置及打开的对象可恢复。右侧 AI 使用独立研究会话，切换标签不会更换会话关联内容。

财务因子按公告日期进入研究。免费数据源的覆盖和历史修订能力以实际数据为准。模型按时间区间训练、验证和测试，寻优在验证区间进行。AI 的服务地址、模型和 API Key 在设置中填写；Ling-3.0-flash-Fin 可作为兼容服务候选，模型权重不随应用交付。

组合支持等权、评分加权、风险平价和均值方差；仓位、单股、行业和换手限制在策略页配置。结果分别展示策略与基准表现，并可查看行业权重、风险贡献、交易和持仓收益贡献。因子方向、MAD 去极值、标准化和可选中性化在因子页设置。

日常使用进入“每日选股”：为已启用策略分配资金占比，在“实际持仓”填写或导入全局持仓、可卖数量与现金，点击“生成合并调仓清单”。软件按需更新数据与模型，合并同一证券的策略权重，保存候选股票、目标组合、策略贡献和一份净调仓清单。未分配资金留作现金，清单金额按最新完成交易日价格估算。生成清单不会改变实际持仓，操作后由用户更新；不包含券商下单。

持仓 CSV / Excel 列为 `证券代码,持仓数量,可卖数量,成本价,可用资金,日期`，成本价可省略。数量以股为单位，日期为 `YYYY-MM-DD`。研究行情及财务文件仍使用 CSV / Parquet。

首次使用免费数据源，先在“股票池”保存证券代码，再到“数据”选择日期并手动更新。数据逐股保存，后台可取消；同一天重新运行相同的未完成批次，会复用已完成的股票。导入已有文件后，可单独点击“保存研究区间”，无需联网更新。

CSV / Parquet 的行情列为 `symbol,date,open,high,low,close,volume`；证券代码支持 `SH600000`、`sh.600000`、`600000.SH` 或六位代码，成交量单位为股。估值因子使用 `peTTM,pbMRQ`。若输入前复权价格，应一并提供 `factor=前复权价/原始价`，用于还原实际成交价和股数；缺少的字段会在数据说明中列出。

财务文件包含 `symbol,announcementDate,reportDate`，其中公告日期不可省略；对应因子字段为 `roeAvg,YOYNI,YOYRevenue,npMargin,liabilityToAsset`。净利率也兼容旧列 `netProfitMargin`；当前 BaoStock 适配未提供收入同比 `YOYRevenue`，使用该因子需导入有明确口径的数据。BaoStock 的 `code,pubDate,statDate` 列名也可直接导入。

历史指数成员可导入 `symbol,startDate,endDate`，历史行业可导入 `symbol,effectiveDate,industry`。免费来源快照按记录日期生效，界面列出覆盖范围；今天的成分或行业不会倒填到较早日期。沪深300和中证500基准行情随免费数据更新保存。

“数据中心”还可下载或导入资金流、筹码与龙虎榜，用于个股全景、条件筛选和因子研究。资金流金额统一为元、占比为比例；筹码是算法估算，成本偏离使用原始股价。免费资金流与筹码历史通常较短，实际覆盖和来源错误会显示在界面；更长历史可通过文件补充。个股资料可按截止日期查看，完整表格分页读取，CSV / Excel 导出保留全部记录。

因子页支持 Qlib 公式，例如 `$close/Ref($close,10)-1`。策略的 Python 编辑器提供 `pd`、行情表 `prices` 和按日期、证券索引的评分 `scores`；修改 `scores` 并保留索引即可，例如 `scores = -scores` 将排序方向反转。撮合、费用和持仓仍由 Qlib 处理。

结果页先看整体表现；因子实验可从汇总进入单因子的 Pearson IC、Rank IC、分组表现、衰减和稳定性。交易与持仓表支持分页和证券/日期筛选，点击一行打开对应行情，可继续加载更早日线。选股实验的 CSV 导出调仓清单，其他实验导出第一张完整结果表；Excel 包含全部表，PDF 为指标、参数和表格预览报告，图表图片单独导出。

## 开发与交付

    npm run typecheck
    npm test
    npm run package:win

npm test 只运行新版研究功能的计算和持久化检查。普通修改选择相关检查，界面修改查看实际页面；整合和交付时再操作完整流程。CI 做一次编译和研究检查，安装包任务手动运行。

Windows 安装包输出在 artifacts/package。项目目录由用户选择，实验索引使用 SQLite，表格数据使用 Parquet。全局保存实际持仓、自选、会话索引、共享数据与工作区布局；项目保存策略、实验和项目内批注。

开发入口：apps/desktop/src/researchMain.ts、apps/desktop/src/renderer、apps/backend/src/v3_backend/research。GUI 和 AI 共用接口，定义见 packages/contracts/src/research.ts。

## 开源模块

Electron、React、Dockview、TanStack Table、Monaco、ECharts、KLineChart；Python 3.12、Qlib 0.9.7、alphalens-reloaded 0.4.6、BaoStock、AKShare、LightGBM、Ridge、Optuna、PydanticAI Slim。上游许可证随相应依赖保留。

本仓库使用 Apache-2.0 许可证。软件用于研究，不包含券商交易连接。
