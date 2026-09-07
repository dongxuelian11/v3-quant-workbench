# V3 开源量化内核与可视化研究桌面

## 当前状态
- 目标：交付日常可用的 Windows A 股日线研究软件，量价和财务多因子选股优先，完成下列首版范围。
- 已完成：需求对齐、A 风格概念选择、开源选型；2026-09-07 刷新 GitHub，开放 PR 为 0；从 main 建立 codex/v3-rebuild，旧分支及文件保留。
- 正在做：精简旧流程、建立共享接口，准备前后端并行开发。
- 下一步：完成数据→股票池→因子→策略→回测→实验比较，再完成模型、寻优、AI、批注、导出与安装包。
- 任务：主任务 01a07ab5-7f36-73c2-8a58-5f6b8b3ae66e；前端/后端/审核任务建立后在此记录。

## 已确认的产品设计
- A 股、日线、多因子选股优先，包含量价、估值、盈利、成长因子。
- A「利落平面」：冷灰白浅色、克制蓝色、适中密度、中文。左项目列表，中间概览/数据/股票池/因子/策略/模型/回测/结果，右 AI，底部任务。窗格拖动、分屏、调整和记忆。
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

视觉参考（用户已选 A；图中为概念示例）：
C:/Users/Administrator/.codex/generated_images/01a07ab5-7f36-73c2-8a58-5f6b8b3ae66e/exec-34adf55e-9617-4438-9ce6-49a21ea32c6b.png

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
2. 真实数据研究闭环与 A 风格 GUI。
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
