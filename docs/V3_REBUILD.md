# V3 开源量化内核与可视化研究桌面

## 当前状态
- 目标：交付日常可用的 Windows A 股日线研究软件，量价和财务多因子选股优先，完成下列首版范围。
- 已完成：从main建立codex/v3-rebuild，GitHub开放PR为0（9月7日开工查询）；Python3.12.14及依赖、Electron39.8.10；桌面桥、B视觉前端和研究后端均已合入；CI/README/打包精简已提交0c6f911。真实Electron已创建项目、保存20股股票池及独立个人模板、提交BaoStock更新；源码限定审核及相关小样本已修停牌成交、寻优参数、复权拼接、移动工件、分页和交易方向。截图见artifacts/research-journey/data-desktop.png。
- 实测完成：6股2024..2025行情和72条公告财务落盘；GUI五因子分析、多因子周调仓、Ridge、LightGBM TPE两次寻优、组合Grid两次试参、模型评分回测与实验比较。CSV464行、Excel四张完整表464/1383/285/2790行、18页PDF和PNG成功导出读取。自定义公式和Python评分反转完成单因子回测；任务取消后重跑、重命名/收藏/删除均通过。四种批注重开/拖动保存、双窗格恢复、侧栏尺寸恢复通过。回放空行情定位已修，实际第二页成交可打开65个标记；单因子查看读取475行IC/换手、5行分组收益。最终打包产物与已安装程序均包含回放修复及短标记。
- 正在做：最终安装包和GitHub草稿PR收尾。安装程序已退出0，安装版使用自身Python重开项目，最后界面更新使用同一最终产物的程序和app.asar，无需重复部署Python。4份旧规则文档提交被自动审批要求 P0_AUTHORITY_AMENDMENT，已问用户，未收到明确回答，保留未提交。AI实连地址/模型也已询问，尚无配置，不把TestModel检查称真实在线/本地连接。
- 下一步：最终安装产物启动复验后提交并推送重构分支，创建同一份草稿PR交付。AI实际在线/本地服务连接待用户配置；4份旧规则草稿的提交待自动审批要求的明确授权。不要重跑已经通过的研究流程或旧全量测试。
- 任务：主任务 01a07ab5-7f36-73c2-8a58-5f6b8b3ae66e；前端 01a07c31-a51e-7901-a91d-b7a15669878c（worktree 63d0）；后端 01a07c32-49f0-75a3-847b-106b1cd50a68（worktree 3170）；审核 01a07c4a-b63d-7300-988b-1d393b4ca42d。三任务均 Astra low。

## 已确认的产品设计
- A 股、日线、多因子选股优先，包含量价、估值、盈利、成长因子。
- B 视觉（2026-09-07 用户在前端任务明确纠正）：暖白、柔和层次、青绿强调、适中密度、中文。左项目列表，中间概览/数据/股票池/因子/策略/模型/回测/结果，右 AI，底部任务。窗格拖动、分屏、调整和记忆。
- 概览突出目标、数据、继续研究和近期实验，打开项目默认概览。
- 股票池个人模板复用，项目副本独立修改。策略模板/参数为主，公式和 Python 入口保留。
- 批量因子筛选后看单因子详情：IC、分组收益、换手、相关性。结果覆盖整体表现、实验比较、交易与持仓回放。
- 每次运行保存独立实验，含参数、数据日期和输出，支持命名/收藏/比较/删除。
- 网格试参与自动优化都要；模型单页设置，常用项展开、高级项折叠。
- 图表指标、买卖点、持仓/交易联动、趋势线、水平线、区间框、文字批注，随项目保存。
- 导出 CSV、Excel、图片、PDF 研究报告。
- 普通用户选择的项目文件夹。旧文件保留，不迁移旧内部格式；CSV/Parquet 导入。
- 免费源优先，手动更新、展示覆盖及日期。首版不做付费 API 页面，可导入供应商文件。
- AI 在线与本地兼容服务都支持。问答/辅助配置/研究推进三模式；研究每阶段结束后与用户讨论再继续，阶段内完成已确定实验。
- 默认结果为整体表现，AI 为辅助配置；组合为多头等权、周调仓，均可修改。

视觉参考（用户最新选 B；图中为概念示例）：
C:/Users/Administrator/.codex/generated_images/01a07ab5-7f36-73c2-8a58-5f6b8b3ae66e/exec-f71f16ab-c0a5-4ce9-924e-41b6bf4dcbf9.png

## 实现选择
- 沿用 Electron/React/Dockview/TanStack Table/Monaco/ECharts；KLineChart 10.0.3 做行情画线。
- Python 3.12，pyqlib 0.9.7，alphalens-reloaded 0.4.6，BaoStock 0.9.3 主源，AKShare 补充，Optuna GridSampler/TPESampler，PydanticAI Slim 兼容服务。
- 项目 Parquet 数据，Qlib 二进制计算缓存，SQLite 实验与任务；配置、代码、批注、结果随项目。
- Alpha158 和财务字段；财务按公告日期处理，复用 Qlib PIT 采集/转换，不能按报告期提前使用。来源历史修订完整性按实际说明。
- 单因子排序/多因子加权/模型评分三种组合模板；上一交易日信号在下一交易日执行，费用/滑点/调仓/持仓数可设置。
- LightGBM 和 Ridge；时间顺序训练/验证/测试，寻优使用验证区间。
- GUI 与 AI 共用研究方法。计算任务子进程运行，推送进度；取消和中断记录保留，允许重跑。
- Ling-3.0-flash-Fin 作为兼容服务候选，在线质量未实测；约 255GB 权重不随安装包分发。

## 分工与顺序
主任务负责接口、Electron 进程桥、运行环境、打包和整合。前端 Astra low 负责 renderer；后端 Astra low 负责 Python research 包及关键计算/持久化测试；审核 Astra low 做集中流程/计算审查。简单重复工作可用 Luna max。
1. 精简旧启动/治理/CI，建立接口和重构基线。
2. 真实数据研究闭环与 B 风格 GUI。
3. 模型、寻优、在线/本地 AI、阶段研究。
4. 画线、回放、导出、Windows 安装交付。
普通改动只做相关检查。样式局部查看；小样本核对日期/复权/公告时间/费用，真实 GUI 主流程与重启持久化，交付前实际安装启动。无例行 SHA256、额外台账或反复全量测试。压缩后读取状态和相关文件继续。

## 连接约定
共享类型 packages/contracts/src/research.ts。桌面提供 window.v3Research.request(method, params)、onEvent(listener)、chooseDirectory()、chooseFiles()、exportFile()。
Python：python -m v3_backend.research.server --app-data <directory>。
stdio 复用现有 Content-Length / Content-Type 头 + UTF-8 JSON framing（runtime/framed_stdio.py 与 main/backendRuntime/framing.ts）：输入 {id,method,params}；输出 {id,result} 或 {id,error:{message}}；推送 {event:JobEvent}。stdout 仅协议，日志 stderr。大表以文件保存，详情默认返回最多 500 行，导出保留全部行。

方法：projects.list/create/open/save/summary、universe.templates/saveTemplate、data.preview、factors.list、jobs.submit/list/cancel、experiments.list/get/update/delete/compare、charts.load/save、settings.get/save、ai.chat、exports.create。
- projects.create {path,name,objective}、open {path}、save {project}；其余项目操作 {projectId,...}。
- jobs.submit {spec:JobSpec}，返回 JobEvent；list {projectId?} 返回 JobEvent[]；cancel {jobId} 返回 JobEvent。
- experiments.list {projectId} 返回 Experiment[]；get {projectId,experimentId} 返回 ExperimentDetails；update {projectId,experimentId,name?,starred?}；delete {projectId,experimentId}；compare {projectId,experimentIds}。
- data.preview {projectId} 返回 {datasets:[{name,rows,symbols,startDate,endDate,columns}],rows:[...]}。
- data.bars {projectId,symbol,startDate?,endDate?} 返回日线数组，每行 date/open/high/low/close/volume，供行情图使用。
- factors.list 返回 FactorDefinition[]。summary {projectId} 返回 {project,data,experiments,jobs}。
- charts.load/save {projectId,symbol,annotations?}；settings.get/save {settings?}；ai.chat {projectId,mode,message,history?}。
- exports.create {projectId,experimentId,format:csv|xlsx} 返回 {path}，桌面选择输出位置；图片/PDF 由 Electron exportFile。
具体 JobSpec.parameters 键由后端实现并及时同步给前端。API key 通过设置页输入，不进版本库；所有结果来自真实任务。

已对齐返回：settings={ai:{baseUrl,model,apiKey,temperature},defaultDataSource}；universe.templates=[{id,name,universe}]，saveTemplate={id?,name,universe}；compare=ExperimentDetails[]。ai.chat 返回 {message,phase,proposals:[{title,description,spec:JobSpec}],experimentIds}。研究阶段由用户一次确认批次后提交jobs，完成后继续讨论下一阶段。

JobEvent.progress=0..1；charts.load/save 返回 {annotations:[]}。Grid searchSpace 各项为候选数组；TPE 支持候选数组或 {type:int|float,low,high,step?,log?}。模型搜索键用 hyperparameters.learning_rate / hyperparameters.alpha 等路径。

experiments.table {projectId,experimentId,table,offset?:0,limit?:200,symbol?,startDate?,endDate?} 返回 {name,columns,rows,total,offset,limit}，最多500行，用于完整回放翻页；图表按日期窗口再取该证券成交。trades price/amount为原始价/实际股数，图表前复权坐标用adjustedPrice；direction=1买/0卖。批量因子 details.unavailableFactors 记录个别失败，全失败仍报错。

当前本机实测项目 artifacts/research-journey/project，id=6c6e6d0c1ed945dc8a81dd3626dd3464；成功数据job=06731d47d76e4f259c83c23e13e455bd，因子=f1db4c274a3847428885ea68bee67dfb，五因子回测=e12574ae76454664ab0d7d8a12963854，Ridge=fec3dcc7e20d46e7bff177fa2a4806af，模型评分回测=05fa4b398f3f40baae2a76794c5283d0，自定义公式/Python回测=0811aa78cb4b4a89a9d7f72266751c3b。旧失败更新f988f28639ab44cd8f3ba8ee7fe7e444保留；逐股保存94deba3已通过。导入项目 artifacts/research-journey/import-project，id=10d933051a1a4c51827f6ed17512b25f。安装目录artifacts/installed-v3，最终产物artifacts/package/v3-quant-workbench-1.0.0-x64.exe。实际检查脚本.cache/installed-check.cjs（最新unpacked检查exec61050；21521/35382/45058已关闭）。正常Windows权限运行，无开发Python配置；截图见artifacts/research-journey/final-trade-replay.png、factor-detail.png。不要重复已通过的整套检查。
