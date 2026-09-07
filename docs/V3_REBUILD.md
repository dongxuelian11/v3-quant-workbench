# V3 开源量化内核与可视化研究桌面

## 当前状态
- 目标：在已交付首版上完成第二轮全部范围：沪深 A 股 2015 年至今的研究补强、四种组合构建、每日目标组合和调仓清单，以及 Ling 真实联调。
- 已完成：从main建立并推送codex/v3-rebuild，已创建[草稿PR #54](https://github.com/dongxuelian11/v3-quant-workbench/pull/54)。开工及9月8日收尾刷新均无旧开放PR。Python3.12.14及依赖、Electron39.8.10、桌面桥、B视觉前端和研究后端均已合入；CI/README/打包已精简。最终Windows安装包已生成并在本机安装启动，使用随包Python，无开发环境覆盖。最终已安装程序截图见artifacts/research-journey/final-desktop.png。
- 实测完成：6股2024..2025行情和72条公告财务落盘；GUI五因子分析、多因子周调仓、Ridge、LightGBM TPE两次寻优、组合Grid两次试参、模型评分回测与实验比较。CSV464行、Excel四张完整表464/1383/285/2790行、18页PDF和PNG成功导出读取。自定义公式和Python评分反转完成单因子回测；任务取消后重跑、重命名/收藏/删除均通过。四种批注重开/拖动保存、双窗格恢复、侧栏尺寸恢复通过。回放空行情定位已修，实际第二页成交可打开65个标记；单因子查看读取475行IC/换手、5行分组收益。最终打包产物与已安装程序均包含回放修复及短标记。
- 当前：第二轮进行中，主分支095003a。已整合前端选股/持仓、因子/模型/组合/验证控件、AI历史/阶段/引用、历史行情加载与基准表；后端持仓/AI路由/分区行情/历史快照及四组合模块已合入。组合14项、AI3项、持仓/历史分区相关检查通过；审核发现回退持仓风险显示P2已由ef27f9e修复。真实Ling仍待用户设置Key（已提问），实际Electron设置页hasKey=false。4份旧规则草稿仍未提交；PR54未合并。
- 下一步：后端继续成交/基准指标、因子标签/滚动模型/寻优及选股编排；前端待最终结果表字段；主任务300股实取、实际窗口整合检查、真实AI、导出与1.1.0安装包。旧首版检查不重跑。数据实测发现全市场行业月快照每次约90秒，后端正调整先行情与按需补行业，并补财务增量缓存。
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

当前本机实测项目 artifacts/research-journey/project，id=6c6e6d0c1ed945dc8a81dd3626dd3464；成功数据job=06731d47d76e4f259c83c23e13e455bd，因子=f1db4c274a3847428885ea68bee67dfb，五因子回测=e12574ae76454664ab0d7d8a12963854，Ridge=fec3dcc7e20d46e7bff177fa2a4806af，模型评分回测=05fa4b398f3f40baae2a76794c5283d0，自定义公式/Python回测=0811aa78cb4b4a89a9d7f72266751c3b。旧失败更新f988f28639ab44cd8f3ba8ee7fe7e444保留；逐股保存94deba3已通过。导入项目 artifacts/research-journey/import-project，id=10d933051a1a4c51827f6ed17512b25f。安装目录artifacts/installed-v3，最终产物artifacts/package/v3-quant-workbench-1.0.0-x64.exe。实际检查脚本.cache/installed-check.cjs，验证会话均已关闭。正常Windows权限运行，无开发Python配置；截图见artifacts/research-journey/final-desktop.png、factor-detail.png。不要重复已通过的整套检查。

## 第二轮已批准范围（2026-09-08）

以下为本轮实际施工依据，覆盖首版中较简单的计算口径。保留旧项目与实验，新运行补齐并保存实际配置。只维护本文件；主任务整合，前后端与审核沿用原任务，Astra low；无例行 SHA256、逐功能审批或反复全量测试。券商下单、北交所、分钟数据不在本轮。

### 数据与执行
- BaoStock 主源、AKShare 补充，沪深 A 股 2015 年至今。增加指数、原始 OHLC、昨收、换手、上市日期、历史行业和成员快照。按证券 Parquet 分区，增量更新、按需补历史、分批取消续传；项目内复用 Qlib 与因子缓存，以数据更新时间和计算配置判断重算。
- 沪深300/中证500按信号日期取历史成分；全市场按历史上市状态。免费快照按其记录日期生效，展示日期/覆盖范围；允许导入成员起止日期。禁止最新成分、行业或市值倒填历史。财务以公告日期可知，修订完整性按来源实际说明。
- 市值中性化用对数流通市值，优先明确流通股本；可用 BaoStock 成交量与换手估算并注明口径。
- 基准沪深300/中证500，股票池自动匹配，其他默认沪深300。新增基准净值、超额、回撤、月度收益、跟踪误差和信息比率。
- T日收盘后信号、T+1开盘成交；原始价格和精度决定涨跌停，覆盖主板/创业板/科创板/ST/IPO历史规则，替代统一9.5%。停牌不成交，涨停开盘不买、跌停开盘不卖。
- 整手、科创板最低申报量、零股卖出、可卖数量和资金不足逐项处理，保存未成交原因。佣金/最低佣金/印花税/过户费/滑点分别配置，印花税按历史日期，记录采用假设。成交量限制使用信号日已知的历史量，不能使用下一日全天量判断开盘成交。

### 因子、验证和组合
- 因子方向 → MAD三倍尺度 → 可选行业/市值中性化 → 截面标准化；中性化分别开关，默认关闭，历史数据缺失显示覆盖。常数因子标为无区分度。
- 因子页提供方向/处理方式/分析周期/分组数。Pearson IC、明确标识 Rank IC、ICIR、累计分组表现、衰减、分期稳定性；因子相关性默认每日截面相关性的平均。
- 交易标签为 T+1 开盘到 T+H+1 开盘收益，跨区间标签剔除；收盘到收盘保留为明确研究选项。默认 H=5，分析1/5/10/20日、5组。
- 单次训练/验证/测试按交易日70/15/15，日期可编辑。滚动为3年训练/6个月验证/1个月测试，按自然月滚动并对齐交易日。复用 Qlib 日历/窗口工具与现有队列，不新增任务系统。
- 模型寻优默认验证集 MSE，组合寻优默认验证集信息比率；支持已实现指标切换，选好参数后再跑独立测试。每个窗口/试参结果保存，用户明确应用最佳参数。测试表现不参与选参。
- 组合四种：等权、非负排名评分归一、真实风险贡献优化的风险平价、均值方差。后两者复用 SciPy/CVXPY/sklearn Ledoit–Wolf/Qlib 薄适配。均值方差历史收益或明确选择的模型收益预测，默认历史；预测评分不能冒充预期收益。
- 共用总仓位、单股上限、行业上限、换手上限。换手=包含现金的权重变化绝对值之和/2。目标30只、周调仓、95%仓位，其余上限默认关闭。
- 协方差与历史收益最近252交易日、至少126有效样本、Ledoit–Wolf；年化口径一致，风险厌恶3。只用信号日前可知记录。
- 有效股票/容量不足保留现金，显示目标与实际仓位和原因。不得自动放宽约束；已有持仓与约束冲突时保留记录/已算结果，标明不可执行及冲突。保存目标和实际成交权重，风险平价显示约束后的实际贡献偏差。

### 每日选股、GUI 与 AI
- 独立“选股”页及概览入口，顶部启用策略/数据日期/模型更新时间/更新并生成，持仓手填或 CSV/Excel 导入，含可卖数量与可用现金。
- 用户明确启用策略与模型方案。一次运行顺序：增量更新 → 到期模型重训 → 最新评分 → 组合 → 调仓清单 → 实验保存。每月首次运行选股时重训，沿用确认参数，自动寻优单独发起。
- 三视图候选股票/目标组合/调仓清单，评分、因子贡献、当前/目标权重、数量、估算金额和不能调整原因。金额用最新完成交易日价格估算。生成清单不改变实际持仓，用户操作后自行更新。
- 常用因子方向/权重、模型和寻优参数使用表格/下拉/数值控件，代码与 JSON 放高级。结果补齐基准/行业/风险贡献/持仓收益贡献；行情按日期窗口加载，可继续向前，取消只能最近500根的限制。沿用 B 视觉和可记忆布局。
- OpenRouter默认 https://openrouter.ai/api/v1，模型 inclusionai/ling-3.0-flash-fin:free，密钥用户设置。PydanticAI 工具读取真实数据概况/配置/实验/相关表，辅助新组合/验证/选股。
- AI 提出阶段 → 用户运行 → AI读实际结果 → 讨论下一阶段；聊天与阶段随项目保存，实验引用可打开。真实连接和三种操作验证后才称已接通，TestModel不算。

### 本轮接口约定
保留四类核心对象。以下为现有 JsonObject 参数的键名约定，不增加另一套配置或身份系统。旧字段继续接受，新运行保存完整默认值。
- 共享 JobKind 加 selection.run；chooseFiles({purpose:"positions"|"membership"|"research"})，缺省仍为研究导入，持仓支持 CSV/XLSX。
- positions.get {projectId}、positions.save {projectId,positions}、positions.import {projectId,path}，均返回 {asOfDate,cash,rows:[{symbol,quantity,sellableQuantity,costPrice?}],updatedAt?}。无文件持仓默认空表现金0，导入错误明确指出行/字段。
- ProjectConfig.settings 使用 selectedFactors/customFactors/backtest/model 原键，增加 factorProcessing、factorAnalysis、selection。因子和模型/回测任务传 factorProcessing；结构 {directions:{factorId:1|-1},winsorize:"mad"|"none",madScale:3,standardize:true,neutralizeIndustry:false,neutralizeSize:false}。
- factorAnalysis/factor.analyze：periods:[1,5,10,20],quantiles:5,labelMode:"next_open"|"close"，以及 factorIds/customFactors/factorProcessing。默认next_open。
- backtest 保留 template/factorIds/weights/topN/rebalance/capital/modelExperimentId/code 等。增加 benchmark:"csi300"|"csi500"，portfolio:{method:"equal"|"score"|"risk_parity"|"mean_variance",grossExposure:0.95,maxWeight:null,industryCap:null,turnoverLimit:null,lookback:252,minObservations:126,riskAversion:3,returnSource:"historical"|"model"}。约束比例范围0..1，null表示未启用。
- costs:{commissionBuy:0.0003,commissionSell:0.0003,minCommission:5,stampDuty:"historical"|number,transferFee:0.00001,slippage:0.001,volumeParticipation:0.1}；旧 commissionBuy/Sell/minFee/slippage 在缺 costs 时兼容，成本假设随实验保存。
- model 保留现有六个日期字段与 hyperparameters/labelHorizon；增加 validation:{mode:"single"|"rolling",trainYears:3,validMonths:6,testMonths:1,stepMonths:1}。单次日期留空由服务生成70/15/15。labelMode默认next_open，实时预测不能要求未来标签。
- optimize.run 保留 target/sampler/trials/baseParameters/searchSpace，增加 objective（model默认valid:mse，backtest默认valid:information_ratio）、validation（含上述mode/窗口及六日期）。details.bestParameters 用于用户明确应用；trial/window表与最终测试单独标识。
- selection:{enabled:boolean,strategy:{完整backtest参数},model:{完整model参数},retrain:"monthly",dataSource:"baostock"|"akshare",updateData:true,financials:true}，用户点击启用才保存 enabled:true。selection.run.parameters 可为此快照，空则用已启用的项目selection。每次快照当前持仓，结果保存 candidates/target_weights/rebalance/positions 表；rebalance 至少 symbol,side,quantity,estimatedPrice,estimatedAmount,reason,currentWeight,targetWeight。量化约束冲突通过 details.executable:false 和 details.conflicts 显示。
- data.bars 增加 beforeDate（严格早于）和 limit（默认500）并保留数组返回；startDate/endDate窗口可往前取，不能永远先截最近500再过滤。experiments.table 原分页保留，新增表沿用现有导出。
- ai.state.get/save {projectId,state?} 返回 {messages:[],phase:"",proposals:[],stageJobIds:[],mode:"assist"}；messages包含 role/content/phase?/experimentIds?，持久化项目内。ai.chat保留既有返回，增加工具读取实验详情及表，不自动执行。

### 实现提醒与已核实依赖
- BaoStock实际支持 query_hs300_stocks(date)/query_zz500_stocks(date)/query_stock_industry(date)；已实取2015与2020成分，记录 updateDate 有时早于请求日；必须用记录日期生效。
- Qlib0.9.7 RollingGen 默认任务扩展会引入完整workflow，使用 ds_extra_mod_func=None 或直接复用 TimeAdjuster 日历窗口送现有队列。月窗口按日历月而非固定21交易日。
- 已安装 SciPy1.15.3/CVXPY1.7.5/sklearn1.9.0，不需要额外组合包。Qlib原RiskParity优化失败也可能返回权重，必须检查求解与实际约束；科创板最少200股但后续递增1股，不能写成200股整手。
- 历史规则：创业板2020-08-24起20%；沪深主板风险警示2026-07-06起10%；注册制主板2023-04-10起首5日无涨跌幅；证券印花税2023-08-28起卖出0.0005，此前0.001。按证券上市阶段和历史ST判断。
- 官方依据：https://www.szse.cn/aboutus/trends/conference/t20200821_580925.html 、https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20260424_10816474.shtml 、https://www.szse.cn/lawrules/service/member/t20260630_621404.html 、https://edu.sse.com.cn/tib/ysptj/c/4868129.shtml 。
- Ling当前服务列出 tools/tool_choice，不支持 response_format；采用PydanticAI工具输出路径。Context7工具本会话不可调用，已查本地安装源码与官方文档，不重复尝试不存在的工具。

### 集中验证与完成状态
- 进行中：后端数据/历史成员/缓存/基准/成交、因子/标签/验证/组合与每日选股；前端持仓/配置/选股及结果页。主任务AI工具与持久化代码已完成，实验表/阶段只读、项目移动重开和服务失败保留问题3项检查通过（仅本地模型替身，不代表真实AI接通）。真实AI/集成导出/安装包待完成。
- 当前实测运行：`.cache/round2-data-check.py cold`，exec session43216，项目artifacts/round2-journey/performance300（id3fc3ea535556450daedac1f4b4197d38），job7d6536065659428eaaaa66a7148d67cd。2024-01-02..2026-09-07的300股手工性能样本，历史来源快照单独保存，非历史策略股票池。先取消15股再自动续传，目前在历史行业补齐阶段；不得另开BaoStock登录并发踢会话。计时与峰值内存写data-measurements.json。最终还需warm、计算冷/热缓存和2015按需补历史。
- 实际Electron验证会话：exec session68381，`.cache/desktop-check.cjs`，appData artifacts/research-journey/app，已打开首版真实项目和模型设置；使用showInactive后可截图，隐藏窗口直接截图会超时。截图artifacts/research-journey/round2-selection-in-progress.png为尚未生成结果的页面。当前运行源码已build至e99dc47（095003a的折叠布局改动尚待下一次集成build）。新窗口实际操作均待后端完整连接后集中完成，勿将页面存在称作选股已可用。
- 针对新增计算用小样本核对成员切换、公告、规则日期、停牌/费用/申报；手算基准/换手/现金/权重/风险贡献；标签边界、验证集选参、滚动衔接、最新预测。
- 集成后一次真实数据研究流程覆盖四组合/持仓导入/清单/保存重开/导出；300股规模记录首次与缓存计算耗时/内存，增量/历史加载/取消续传。
- 用户在设置填写Key后，Ling完成辅助配置/解释真实实验/一阶段研究讨论。最终更新Windows安装包，一次实际安装启动和关键流程检查。缺少真实验证保持待完成，不用模拟结果替代。
