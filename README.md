# V3 量化研究工作台

[English](README.en.md) · [下载安装包](https://github.com/dongxuelian11/v3-quant-workbench/releases/tag/v1.8.0) · [当前状态与下一轮计划](docs/V3_REBUILD.md)

面向 Windows 的沪深 A 股量化研究桌面。通过中文界面连接开源 Python 计算模块，将数据、因子、模型、日线策略、回测和研报放在同一个本地工作区。

**当前版本：1.8.0，研究预览版。** 新增固定输入复现、独立选股器、每日研究方案、设置中心及本地命令助手入口。软件不附带完整 A 股历史数据库或研报全文库；安装后需要获取或导入数据。千股五年性能、完整研报／RD-Agent 在线研究、本地助手完整界面流程与部分桌面场景尚未完成验收，不能视为整轮计划全部完成。

## 可以做什么

| 工作 | 已实现的能力 |
|---|---|
| 行情与数据 | 股票、指数及板块入口，免费源与文件导入，日线和可用分钟行情，自定义 N 交易日图、画线与多窗口 |
| 因子 | 量价与财务因子、公式、方向、MAD、标准化、可选中性化，以及 IC、Rank IC、分组表现和覆盖分析 |
| 模型与组合 | Ridge、LightGBM、时间区间与滚动验证、Optuna；等权、评分加权、风险平价和均值方差 |
| 策略与回测 | 完整日线交易规则、费用与成交限制、基准对比、持仓及全部记录股票的模拟买卖点 |
| 日常选股 | 多策略资金分配、全局持仓导入、目标组合与合并调仓清单、日线模拟账户；生成清单不修改实际持仓 |
| 研报与 AI | PDF／网址导入、全文检索、主题订阅、页码阅读、按需 OCR、复现方案；项目会话、真实研究工具与 OpenUI 表单 |
| 结果管理 | 独立实验与配置记录、比较、CSV／Excel、图表图片和 PDF 预览报告导出 |

分钟行情用于看盘；训练、回测和模拟账户使用日线。软件没有券商下单功能。

## 安装与第一次使用

从 [v1.7.2 Release](https://github.com/dongxuelian11/v3-quant-workbench/releases/tag/v1.8.0) 下载 `v3-quant-workbench-1.7.2-x64.exe`，适用于 Windows x64。安装包包含 Python 解释器和基础研究依赖，不需要另外安装 Python；OCR 模型按需安装，AI 模型权重不随包提供。

1. 启动进入干净首页，打开或新建项目，明确股票范围和日期。
2. 获取免费行情／财务数据，或导入自己的文件，先检查实际覆盖。
3. 分析因子，配置策略或模型，运行日线回测。
4. 在结果中查看基准、持仓和个股买卖点，比较并导出实验。
5. 需要每日选股时，明确应用策略、资金占比及当前持仓，再生成清单。

AI 服务地址、模型和密钥在软件设置中填写。普通研究无需连接 AI。数据源失败时查看错误和已有覆盖，重试或文件导入；不要把目录中的证券数量理解为已下载历史数量。

## 数据与计算口径

- 行情 CSV／Parquet 基础列：`symbol,date,open,high,low,close,volume`，成交量单位为股。推荐显式交易所代码，如 `SH600000`、`SZ000001`；上证指数为 `SH000001`。
- 前复权导入需提供 `factor=前复权价/原始价`，供成交价和股数还原使用。财务数据需有 `symbol,announcementDate,reportDate`；缺少公告日期不能按季度结束日提前使用。
- 历史成员可导入 `symbol,startDate,endDate`，历史行业可导入 `symbol,effectiveDate,industry`。免费快照按其记录日期生效，不声称具备完整历史。
- 持仓 CSV／Excel 列：`证券代码,持仓数量,可卖数量,成本价,可用资金,日期`；数量为股，日期为 `YYYY-MM-DD`，成本价可省略。
- 回测采用日线信号和下一交易日开盘执行，处理滑点、佣金、最低佣金、历史印花税及交易限制。它不是盘口撮合模拟；其他成本按保存的配置计算。
- 项目目录保存配置和实验；全局目录保存共享缓存、持仓、会话与研报。源码和安装包不包含个人项目、API 密钥、研究数据或研报原文。

## 已验证与已知限制

安装版已验证真实文本研报导入、20 页阅读、扫描派生页 OCR、方案编辑与运行、结果比较及原生导出。六股真实样本的 43 笔回测成交逐笔匹配日期、方向和价格。1.7.2 修复并复查了方案刷新、未保存草稿保留和标签重开同步。

这些检查不是全市场数据完整性、策略有效性或全部模块无缺陷的证明：

- 通达信微盘股 `880823` 在线获取在本次验证中未成功，可使用本机通达信或文件导入；不会换成另一条指数曲线。
- 免费行情、历史成分、行业、财务修订及另类数据的覆盖取决于来源。没有预装完整的 2015 年至今研究库。
- Ling 真实服务成功读取报告并保存过方案，也出现参数缺失和引用错误；需要监督使用。OpenUI 部分安装验证使用真实方案离线回放，不代表在线自主研究全链稳定成功。
- RD-Agent 完整多轮恢复尚未验证；托盘右键停止尚未完成安装操作验证。运行中关窗继续及托盘返回已验证。
- 点击运行后、任务提交前立即关窗，可能仅保存方案，需要重新打开明确运行。PDF 导出是指标与表格预览，不是全部原始记录。

## 从源码运行

Windows 开发使用 `.node-version` 指定的 Node.js（当前 24.16.0）和 Python 3.12：

```powershell
npm ci
npm run setup:research
npm start
```

指定 Python 路径：

```powershell
npm run setup:research -- --python "C:/Python312/python.exe"
```

`npm run dev` 启用开发热更新；`npm run build` 执行类型检查并构建桌面；`npm run package:win` 在 `artifacts/package` 生成安装包。运行时位于 `runtime/research-python`。

计算或持久化修改做相关检查，界面修改检查实际操作；`npm test` 用于研究套件整合验证，不要求每个小改动重复全量运行。见 [贡献说明](CONTRIBUTING.md)。

## 架构与开源模块

Electron／React 桌面通过共享接口调用一个本地 Python 服务。复用 Qlib、Alphalens、BaoStock、AKShare、Optuna、LightGBM、scikit-learn、PydanticAI；界面采用 Dockview、TanStack Table、Monaco、ECharts、KLineChart、HQChart、PDF.js 和 OpenUI。文本解析使用 pdfplumber，OCR 使用按需安装的 RapidOCR，通达信适配采用隔离依赖。

接口位于 `packages/contracts/src/research.ts`；桌面入口为 `apps/desktop/src/researchMain.ts`，研究服务位于 `apps/backend/src/v3_backend/research`。

## 项目状态与许可证

公开 `main` 从重构版本建立新的提交历史；被替代的旧开发分支及旧发布已归档至维护者本地。下一轮计划在 [V3_REBUILD.md](docs/V3_REBUILD.md)，明确区分已交付与待实施。

本项目使用 [Apache-2.0](LICENSE)。上游组件与数据内容遵循各自许可证和使用条款；软件许可证不授予第三方研报或数据的再分发权。
