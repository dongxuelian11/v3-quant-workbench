# V3 V1.1 — Usable Research Product 可执行计划

状态：PLAN_READY

生成日期：2026-08-23（Asia/Shanghai）

用途：供 GPT-5.6 Luna Max 在一次长期 Codex 任务中直接执行。本文是执行合同，不是愿景稿。

## 1. 版本目标

V1.1 的唯一产品目标：

> 第一次使用 V3 的普通用户，不接触源码、不依赖 Demo，能够在一个真实项目中导入或获取 A 股日线数据，创建并验证一个因子，生成可解释的 long-only 策略，运行研究级回测，查看真实结果，退出后重启并继续。

V1.1 的发布名：

    V3 V1.1 — Usable Research Product

V1.1 的最高能力声明：

- 产品状态：PRODUCT_CONNECTED
- 研究状态：RESEARCH_ONLY
- 数据/结果 admission：PRE_ALPHA
- formal truth：NOT_FORMAL
- Public Alpha：NOT_CLAIMED
- 实盘、模拟经纪、L2/L3 Agent 执行：NOT_AVAILABLE

完成条件不是“代码很多、测试很多或 CI 绿色”，而是本文定义的 Golden Journeys、故障注入、重启持久化和 clean-machine 产品验收全部通过。

## 2. 本计划采用的 CURRENT

规划快照：

- Repository：dongxuelian11/v3-quant-workbench
- remote main：02c5b8748170569ffc436f3bf5d2f682c21d2811
- exact-main tree：e3f3d3155177c17580015f4ef5b5405d0b689774
- PR #49：MERGED，merge commit 为 02c5b8748170569ffc436f3bf5d2f682c21d2811
- PR #49 reviews：空
- open PR：0
- open issue：0
- main CI：SUCCESS
- packaging-clean-machine-evidence：SUCCESS
- 计划分支：codex/v1-1-usable-research-product-01
- 计划分支在规划时：NOT_FOUND

本地 D:\V3OpenSource 根 checkout 是旧提交且 materially dirty。它只可读，不允许 reset、clean、stash、checkout、覆盖或拿来实施。正式实施必须从执行时重新查询到的 GitHub CURRENT 建立新的 clean worktree。

## 3. 项目权威与不可越界项

当前 Authority version 为 1.0.2。规划时全部哈希匹配：

- V3_PROJECT_CONSTITUTION.md：92ff8049addd10c1ca7f6ca293007b254045f3f63bae53ddc626b761da5bd32b
- AGENTS.md：cbe7d78e2eccbfd5254fd08b30a0b145dc7c37b60aa5eadbbf4649b490f5b385
- V3_CANONICAL_ARCHITECTURE.md：ca74dcd00d2d20ba106d962b2455254f8ee69807df09d20ff4984e20a362bc5b
- V3_CAPABILITY_LEVELS.md：79ca5210a33f283332884a9a4268e08a093ffe2d4ea33fe97d20672d355a9266
- Authority Manifest：3306f51f4d9b26577f092d53e3a5cdb319619e9e9a75c0b90203c87bd21c425a

原始请求没有 P0_AUTHORITY_AMENDMENT 授权。因此：

- 禁止修改四个 P0 authority 文件及其 Manifest。
- 如果实施需要改变 doctrine，立即 STOP_FOR_REVIEW。
- 任何 authority hash 漂移，立即 STOP_FOR_REVIEW。
- 不允许把 PRE_ALPHA、NOT_FORMAL、NOT_AVAILABLE、NOT_RUN、PENDING 或 BLOCKED 升级为更强结论。

## 4. 交付拓扑

只允许一个 program、一条 branch、一个 PR、四个 checkpoint commit：

1. C1 Product Shell + Runtime Truth
2. C2 Data + Factor Research
3. C3 Strategy + Backtest + Final Result
4. C4 Usability + Release Qualification

固定 lineage：

- branch：codex/v1-1-usable-research-product-01
- final PR：一个
- 禁止 R2/R3、Closure-A/B、递归修复 PR
- 禁止 rebase、reset、force push、amend、auto-merge
- 同一 finding 只在同一 PR 中做一次有界修复；若无法闭合则 STOP_FOR_REVIEW
- 最终状态必须是 OPEN / UNMERGED / STOP_FOR_INDEPENDENT_REVIEW

建议的四个 commit message：

1. feat(v1.1): establish truthful project runtime and product shell
2. feat(v1.1): connect data and factor research
3. feat(v1.1): connect strategy backtest and finalized results
4. feat(v1.1): qualify the usable research product

每个 checkpoint 只有在其验收全绿、Ledger 已更新、authority hash 未漂移后才可 commit 和 push。

## 5. 深度设计结论

### 5.1 两份审查材料不是两条路线

“Runtime Integrity”不能再单独做成无限地基工程；“Usable Research Product”也不能绕开运行时真值。每个 checkpoint 同时交付一个可见产品增量和支撑该增量的最小真实性闭环。

### 5.2 必须拆开单标的研究与横截面因子评价

原提案中的一条验收逻辑不成立：

    600519 单标的
    → IC / RankIC / 五分位收益

单标的可以验证价格图、均线、金叉/死叉、信号时序和单资产回测，但不能产生有意义的横截面 IC 或分层收益。因此 V1.1 有两个相互关联、但不能混淆的 Golden Case。

Golden Case A — 单标的可视研究：

- symbol：600519
- 数据区间：2018-01-01 到实际获取的最新完整交易日
- 公式：
  - MJ = AMOUNT / VOL / 100
  - MA5、MA20、MA60
  - GOLDEN_CROSS = CROSS(MA20, MA60) AND MA5 > MA20
  - DEATH_CROSS = CROSS(MA60, MA20) AND MA5 < MA20
- 可证明：真实 K 线、真实因子值、信号点、next-session 执行、单资产回测、结果与重启恢复
- IC、RankIC、分层收益：INSUFFICIENT_SAMPLE

Golden Case B — 横截面因子评价：

- 静态 user-defined Universe，至少 20 个有效标的
- 至少 20 个可评价交易日
- 每个日期至少 20 对有效 factor/forward-return 样本
- 可证明：date-wise IC、RankIC、IC mean/std/ICIR、五分位收益、long-short spread、turnover、coverage、missing rate
- 数据入口可为用户本地 CSV/Parquet；不得伪装成 provider 数据

UI 必须在 Case A 明确显示：

    INSUFFICIENT_SAMPLE
    CROSS_SECTION_REQUIRES_AT_LEAST_20_INSTRUMENTS

不得显示 0、随机值、历史 fixture 或灰色但看似真实的图。

### 5.3 2018 至今数据范围不等于 2018 至今回测权威范围

当前成本策略从 2023-08-28 起才有已编码覆盖，且免费源不提供完整 ST、停牌、涨跌停、公司行动、available-time 和 revision authority。

因此：

- 价格/因子可视区间可从 2018-01-01 开始。
- 回测区间必须是数据区间与已发布 ExecutionPolicy coverage 的交集。
- 如果 V1.1 没有补齐 2018 至今全部制度版本，UI 必须阻止越界回测并显示可用起止日期。
- V1.1 最低放行标准是一个多年度、连续且无 policy gap 的已验证区间；不得为了满足文案而把 2018 之前/之后规则向外延伸。

### 5.4 不用“大重写”解决单体问题

product_runtime.py 和 product_research.py 是热点单体，但 V1.1 禁止整体重写。采用 strangler seam：

- 先为现状补 characterization tests。
- 新能力进入独立 application services。
- 旧 facade 只改为委托新 service。
- 每次只移动一个 owner 的编排，不同时重写状态机、Schema、transport 和 UI。
- 旧内容哈希语义与已有 immutable IDs 不得被重新解释。

### 5.5 不兑现的契约必须撤回能力声明

现有 BacktestService.v1.submitBacktest 契约承诺 checkpoint/resume 与更完整的 A 股前置条件，而产品实现尚不能兑现。V1.1 不允许继续用 FORMAL capability 掩盖差距。

V1.1 采用：

- 旧 BacktestService operation 保持 wire compatibility，但 capability 降为 UNAVAILABLE，reason_code 为 FORMAL_EXECUTION_CONTRACT_NOT_CLOSED，除非本 PR 真正实现其全部契约。
- V1.1 产品回测走新增的、加法式 Product Entry 研究级 operation，明确返回 RESEARCH_ONLY / PRE_ALPHA / checkpoint_resume=UNAVAILABLE。
- resume 控件不显示；TaskService.v1.resumeTask 不绑定。
- 真实 cancel、deadline、retry-from-start 必须实现。

这不是降级产品价值，而是把“可用研究回测”和“正式执行权威”分开。

## 6. V1.1 产品数据流

完整数据流：

    Renderer user intent
    → typed preload IPC
    → Electron ProductBridge
    → correlated runtime request
    → durable Task acceptance
    → isolated product worker
    → provider/local raw byte capture
    → RawCapture + normalization receipt
    → immutable Snapshot
    → explicit UniverseVersion
    → FormulaDocumentVersion
    → FactorDefinitionVersion
    → FeatureMaterialization
    → FactorAnalysisResult
    → StrategyDefinition
    → Signal
    → TargetWeight owner
    → RiskPolicy owner
    → ResearchBacktestRunSpec
    → deterministic engine
    → publication intent
    → Result reconciliation
    → Result VALID or INVALID
    → analytics artifact/read model
    → project-scoped renderer state

任何一步 unavailable：

- 不创建下游 canonical owner。
- 不自动换 provider。
- 不用 fixture 补齐。
- 不显示成功。
- 失败 receipt 必须包含 reason_code、operation_id、correlation_id、project_id 和可安全展示的 details。

## 7. 新增或扩展的核心契约

### 7.1 ProjectScopeToken

Desktop 和 renderer 所有异步结果必须绑定：

- project_id
- project_context_revision_id
- binding_generation
- request_id

ProjectScopeToken 在项目切换时整体更换。异步 completion 的 token 与当前 token 不一致时只记录 LATE_SCOPE_RESULT_DROPPED，不得写入 store。

### 7.2 ControlEnvelopeV1

以下 control frame 全部改为相关联的 closed shape：

- runtime.health
- runtime.prepareShutdown
- runtime.commitShutdown
- productEntry.*
- artifactStream.*

公共字段：

- kind
- control_request_id：UUIDv7
- runtime_generation：正整数
- deadline_at：RFC3339 UTC 或 null

响应必须原样回显 control_request_id 和 runtime_generation。Supervisor 只接受当前 generation 且有活跃 pending slot 的响应。

Supervisor 边界：

- pending control requests：最多 32
- completed/timed-out tombstones：最多 256，TTL 5 分钟
- health 同一 generation 只允许 coalesce，不允许永久占位
- 超时立即清 slot 并写 tombstone
- late reply：丢弃，不得满足后续请求

### 7.3 OperationContext

RequestRouter handler 从只收 body 改为收 body + OperationContext：

- request_id
- operation_id
- project_id
- project_context_revision_id
- deadline_at
- cancellation_token

deadline 规则：

- 已过期请求在 handler 前拒绝，reason_code DEADLINE_EXCEEDED_BEFORE_DISPATCH。
- command enqueue 后把 execution_deadline_at 持久化到 Task/Attempt。
- worker 到期后先 cooperative cancel，5 秒后 terminate，2 秒后 kill。
- query 在每个有界分页/IO 边界检查 deadline。

RequestRouter transport dedupe：

- LRU 上限 4096
- TTL 10 分钟
- 同 request_id 不同 fingerprint 在窗口内仍为 ProtocolViolation
- durable command 幂等继续由 SQLite idempotency owner 负责

### 7.4 BindingActivationV2

项目切换不是“写文件后尝试重启”，而是以下事务协议：

1. 读取并保留 prior active binding。
2. 将 candidate 写入同目录 pending 文件并 fsync。
3. shutdown prior backend，等待真实 exit；超时后 terminate，再超时后 kill。
4. 用 candidate 启动新 runtime generation。
5. 后端在 ready 前验证 project/context ownership。
6. restoreSession 必须成功并返回精确 project/session/context。
7. Electron 复核 candidate read model。
8. 原子 rename pending 为 active binding，并 fsync parent directory。
9. 发布新的 ProjectScopeToken。
10. 之后才通知 renderer 切换成功。

任一步失败：

- active binding 文件保持 prior。
- candidate generation 被完整终止。
- prior binding 被重新启动并验证。
- UI 返回 BINDING_ACTIVATION_FAILED，不能显示新项目已连接。

崩溃恢复：

- active 文件是唯一 commit marker。
- 只存在 pending 时忽略并隔离 pending，启动 active。
- active 已是 candidate 时按 candidate 启动。
- BindingStore 只把 ENOENT 解释为未绑定；JSON 损坏、权限和 I/O 错误必须显式报错。
- session_id 一旦绑定 project_id 后不可改绑；切换项目必须创建新 session_id。

### 7.5 LocalDataImportIntentV1

Renderer 不传任意文件路径。Electron native chooser 打开文件并创建一次性 capability token；renderer 只得到：

- display_name
- byte_size
- media_type
- capability_token

Backend staging 通过有界流接收实际 bytes，再计算 SHA-256。安全要求：

- 读取前 lstat；拒绝 symlink/reparse point 和非 regular file。
- 从已打开 handle 流式复制，避免 readdir/readFile TOCTOU。
- 不先整文件读入内存。
- 单文件最大 256 MiB。
- 最大 2,000,000 rows。
- 最大 2,000 instruments。
- CSV 只接受 UTF-8/UTF-8-SIG、逗号分隔、closed header。
- Parquet 只接受 flat primitive schema；先校验 metadata、row groups、column count 和 logical types，再 batch read。
- nested/list/map/extension/object columns：拒绝。

必需列：

- symbol
- date
- open
- high
- low
- close
- volume
- amount

导入时必须由用户明确声明：

- volume_unit：SHARES 或 HANDS
- amount_unit：CNY
- timezone：Asia/Shanghai
- adjustment：UNADJUSTED

可选列：

- available_time
- is_suspended
- is_st
- tradable
- price_limit_up
- price_limit_down
- no_price_limit_session
- corporate_action_ref

缺失字段必须保持 UNKNOWN，不能 String coercion 或 false default。

规范化不变量：

- key 为 symbol + session_date，重复即拒绝。
- open/high/low/close 必须有限、为正，且 low <= open/close <= high。
- volume/amount 非负；缺失用显式 null + reason。
- sort order 固定为 session_date、instrument_id。
- raw bytes、schema mapping、unit mapping、normalization diagnostics 各有不可变 artifact/ref。
- CSV 与 Parquet 表达相同数据时必须生成相同 normalized payload hash。

### 7.6 FactorPanelV1

现有 TDX parser/translator 必须复用。禁止在 renderer 再写一个硬编码公式解释器。

V1.1 Operator Registry 是新版本，保留旧定义不变。每个 operator 增加 evaluation_axis：

- ELEMENTWISE：ADD、SUBTRACT、MULTIPLY、DIVIDE、比较、AND、OR、NOT、IF
- TIME_SERIES_PER_INSTRUMENT：MA、EMA、REF、HHV、LLV、SUM、STD、CROSS
- CROSS_SECTION_PER_DATE：RANK

Evaluator 的 canonical table key：

- session_date
- instrument_id
- value
- missing_reason

关键语义：

- MA 映射现有 SMA 语义。
- REF 映射正 lag；禁止负 lag。
- CROSS 只在前一和当前值均存在时计算。
- RANK 必须按同一 session_date 的 cross-section 执行，不能把时间序列当横截面。
- IF 的 condition 必须是 boolean series。
- 所有 warmup 输出显式 null，不得补 0。
- AMOUNT/VOL 的单位先由 DataSemanticProfile 归一；MJ 不允许依赖隐式“VOL 是手还是股”猜测。
- 因子 ID 由 source、AST、operator registry version、data semantic profile 和参数共同 content-address。

### 7.7 FactorAnalysisSpecV1

V1.1 固定的可比较评价规范：

- forward_return_horizon_sessions：5
- formation price：RAW_CLOSE at t
- label price：RAW_CLOSE at t+5
- signal availability：after session t close
- quantiles：5
- minimum instruments per evaluated date：20
- minimum valid IC dates for aggregate IC mean/std/ICIR：20
- nonconstant factor and return vectors required
- missing/coverage 以原 Universe membership 为分母

每个日期先计算 Pearson IC、Spearman RankIC 和 quantile returns，再按日期聚合。禁止把所有 symbol/date 样本池化后计算一个相关系数。

状态规则：

- n < 20：INSUFFICIENT_SAMPLE
- factor 或 return 常数：NOT_AVAILABLE / CONSTANT_INPUT
- 有效 IC 日期 < 20：aggregate IC/ICIR 为 INSUFFICIENT_SAMPLE
- IC std = 0：ICIR 为 NOT_AVAILABLE / ZERO_VARIANCE
- year-by-year 样本不足：该年单独 INSUFFICIENT_SAMPLE

### 7.8 ResearchStrategySpecV1

V1.1 不先重做复杂 React Flow。产品 UI 只 author 一个 bounded spec：

- universe_version_id
- entry_signal_factor_version_id
- exit_signal_factor_version_id
- position_sizing：SINGLE_ASSET_FULL_WEIGHT 或 EQUAL_WEIGHT_ACTIVE_SIGNALS
- max_positions：1..20
- gross_exposure：0..1
- rebalance：NEXT_OPEN_AFTER_SIGNAL
- cost_policy_version_id
- execution_policy_version_id
- risk_policy_set_version_id
- initial_cash
- assumption_profile_id

编译后的 canonical chain仍由现有 Strategy、Portfolio、TargetWeight 和 RiskPolicy owners 负责。Renderer 不传 numeric target weights 作为权威。

时序不变量：

- t 日收盘后才可形成 t 日信号。
- 最早在下一个 admitted open 执行。
- 禁止同一根 bar 的 close 信号在同一根 bar 的 open 成交。
- 信号缺失不等于 false；按 spec 的 explicit missing policy 处理。

### 7.9 ResearchExecutionPolicyV1

两种明确 profile：

STRICT_FAIL_CLOSED：

- unknown suspension/tradability/limit state 阻止该订单。
- 不允许用 bar presence 推断正式交易状态。

RESEARCH_APPROXIMATE：

- 可采用“存在有效 bar 且 canonical volume > 0”作为研究近似。
- 每个近似必须进入 AssumptionReceipt。
- 结果固定为 RESEARCH_ONLY / APPROXIMATE / PRE_ALPHA。
- UI 必须持续显示近似 badge，不能藏在详情页。

两种 profile 都不得被宣传为 formal execution truth。

最低执行语义：

- long-only
- T+1 sellability
- lot/minimum quantity
- cash constraint
- explicit commission/stamp/transfer/exchange fees
- fixed-bps slippage
- daily volume participation cap
- unavailable price reject
- suspension/limit handling according to selected profile
- corporate actions only for admitted cases

成交量参与：

    volume_cap = floor(canonical_volume_shares * participation_rate)
    fill = min(requested, lot_rounded(volume_cap), sellable_or_buyable, affordable)

现金不足不得逐 lot 线性递减；用 O(log lots) 的二分求最大可负担数量，最后重新计算费用并验证 cash >= 0。

初始持仓 acquired_on 必须 <= first_session_date。

遇到 rights issue、fractional entitlement、delisting 或未支持 action：

- 在 run preflight 阶段拒绝。
- reason_code 为 CORPORATE_ACTION_NOT_AVAILABLE。
- 不得忽略后继续。

### 7.10 PublicationIntentV1 与 Result Finality

SQLite 与文件系统不能假装成单事务。新增 durable saga：

PublicationIntent states：

1. STAGED
2. BYTES_PUBLISHED
3. CATALOG_COMMITTED
4. RECONCILING
5. FINALIZED
6. FAILED

流程：

1. 流式 stage bytes，得到 hash/size。
2. SQLite 先写 PublicationIntent、预期 descriptors、owner refs 和 Task/Attempt identity。
3. 将 stage 原子 publish 到 content-addressed final path。
4. SQLite 同一事务写 artifact descriptors、references、Result PENDING_RECONCILIATION，并把 intent 置 CATALOG_COMMITTED。
5. 运行 ledger reconciliation。
6. 发布 reconciliation receipt 与 analytics artifact。
7. SQLite 同一事务把 Result 置 VALID、写 finalized_at、登记所有 task_output rows，并把 Task/Run/Attempt 置成功。

任何 reconciliation 失败：

- Result 置 INVALID。
- Task 置 FAILED，category 为 RESIDUAL_VALIDATION_FAILED。
- 已发布证据保留且可诊断，但不能作为成功结果。

重启 recovery：

- STAGED：检查 staging/final bytes，继续或失败。
- final bytes 已存在但 Catalog 未提交：按 hash 验证后补 Catalog。
- Catalog 已提交但未 reconcile：重跑 deterministic reconciliation。
- deduplicated bytes 不允许因单个 intent 失败而删除。
- 无 intent 的历史 orphan 只能进入显式 GC candidate，不能静默删除。

Result reconciliation 至少验证：

- result artifact content hash
- ledger sequence 连续
- order/fill/fee 一一对应
- cash ledger balance
- position ledger balance
- T+1 sellability consistency
- end-of-day NAV = cash + marked holdings
- result/run/project ownership
- all required artifact references active and reachable

Task 在 Result VALID 前不得进入 SUCCEEDED。

Task output 改用 relational rows：

- task_id
- output_role
- ordinal
- owner_type
- owner_id
- artifact_id 可空

禁止用一个 role-keyed JSON map 覆盖同 role 多 artifact。

### 7.11 Artifact Stream 与 Export

Artifact descriptor、stream、export 都必须先证明 artifact 从当前 project 可达。

Stream：

- ticket 绑定 project_id、artifact_id、range、runtime_generation、expiry。
- consume 使用 artifactStream.consume control frames。
- 每 chunk 最大 256 KiB，包含 offset、bytes(base64)、chunk_sha256。
- complete 包含总 byte count 与 artifact SHA-256。
- ticket 一次性；过期/已消费/跨 generation 均拒绝。
- ticket registry 上限 128，并在创建/消费时驱逐过期项。

Export：

- 用户通过 native dialog 选择 destination；renderer 只持 opaque token。
- Electron 从 backend stream 写 destination.tmp，fsync，校验 SHA-256，再原子 rename。
- export manifest 记录目标文件名、bytes、hash、completed_at。
- 只有真实文件写完后 Task 才成功。
- 用户取消 chooser：NOT_RUN，不创建 Task。

GC：

- V1.1 不新增用户可见“立即清理”按钮。
- planGarbageCollection 保持只读 plan。
- execute GC 为 DEFERRED / NOT_AVAILABLE，除非本 PR 同时实现确认、租约、重验 reachability 和恢复。

## 8. 资源 admission

所有边界在创建大对象前检查：

- request frame：1 MiB
- canonical JSON control artifact：16 MiB（沿用现有上限）
- local source file：256 MiB
- normalized rows：2,000,000
- instruments：2,000
- provider symbols per Task：50
- provider concurrency：2
- sessions per backtest：3,000
- instruments per backtest：500
- sessions × instruments：1,000,000
- scheduled weight vectors：3,000
- orders/fills hard bound：2,000,000
- experiment cells：V1.1 产品入口隐藏；formal worker closure前 NOT_AVAILABLE
- worker concurrency：min(4, max(1, cpu_count - 1))
- heartbeat interval：2 秒
- lease expiry：10 秒

超界统一为 RESOURCE_REJECTED，并返回具体 limit/observed；不得因 MemoryError 后才失败。

## 9. 预计写集

这是 owner 边界，不是要求一次性创建所有文件。实施者应尽量缩小实际写集。

Backend：

- apps/backend/src/v3_backend/runtime/request_router.py
- apps/backend/src/v3_backend/runtime/composition_root.py
- apps/backend/src/v3_backend/runtime/product_facades.py
- apps/backend/src/v3_backend/runtime/product_runtime.py
- apps/backend/src/v3_backend/runtime/product_research.py
- apps/backend/src/v3_backend/runtime/product_task_coordinator.py（新增）
- apps/backend/src/v3_backend/runtime/product_publication.py（新增）
- apps/backend/src/v3_backend/runtime/product_data.py（新增）
- apps/backend/src/v3_backend/runtime/product_factor.py（新增）
- apps/backend/src/v3_backend/runtime/product_strategy.py（新增）
- apps/backend/src/v3_backend/runtime/product_results.py（新增）
- apps/backend/src/v3_backend/workers/product_worker.py（新增）
- apps/backend/src/v3_backend/adapters/local_data/（新增）
- apps/backend/src/v3_backend/adapters/tdx_formula/*
- apps/backend/src/v3_backend/domain/factors/*
- apps/backend/src/v3_backend/domain/backtest_runtime/*
- apps/backend/src/v3_backend/domain/result_analytics/*
- apps/backend/src/v3_backend/migrations/versions/0005_v1_1_research_product.sql（新增）
- 相应 backend tests

Desktop/Main：

- apps/desktop/src/main/backendRuntime/supervisor.ts
- apps/desktop/src/main/backendRuntime/processFactory.ts
- apps/desktop/src/main/productRuntime/bindingStore.ts
- apps/desktop/src/main/productRuntime/productBridge.ts
- apps/desktop/src/main/productRuntime/artifactTransfer.ts（新增）
- apps/desktop/src/main/productRuntime/localDataImport.ts（新增）
- apps/desktop/src/main/productRuntime/ipc.ts
- packages/contracts/src/index.ts 或拆出的 V1.1 typed contract module
- 对应 Node tests

Renderer：

- apps/desktop/src/renderer/productRuntimeStore.ts
- apps/desktop/src/renderer/App.tsx
- apps/desktop/src/renderer/Workbench.tsx
- apps/desktop/src/renderer/components/ResearchPanels.tsx
- apps/desktop/src/renderer/components/FactorWorkbench.tsx
- apps/desktop/src/renderer/components/StrategyPanels.tsx
- apps/desktop/src/renderer/components/BacktestResultPanels.tsx
- apps/desktop/src/renderer/components/ResultAnalyticsPanel.tsx
- 新的 Home、Data、TaskFeedback、ProjectScope components/stores
- 对应 renderer/node smoke tests

Release/CI/docs：

- .github/workflows/ci.yml
- .github/workflows/packaging-clean-machine-evidence.yml
- package.json
- electron-builder.yml（仅依赖或资源清单确有需要时）
- scripts 中 V1.1 product、package、clean-machine drivers
- docs/release/V1_1_USABLE_RESEARCH_PRODUCT.md
- docs/release/V1_1_USABLE_RESEARCH_PRODUCT_STATE_LEDGER.md
- docs/status/CURRENT_STATUS.md
- docs/status/V3_DEFERRED_GAPS.md
- docs/architecture/PRODUCT_SURFACE.md
- README.md

P0 authority 文件不在写集中。

## 10. 实施启动协议

实施任务的第一个动作不是编辑代码。

### 10.1 强制读取顺序

1. 完整读取 V3_PROJECT_CONSTITUTION.md。
2. 完整读取 docs/architecture/V3_CANONICAL_ARCHITECTURE.md。
3. 完整读取 docs/status/V3_CAPABILITY_LEVELS.md。
4. 完整读取原始用户请求和两份附件。
5. 完整读取本计划。
6. 完整读取 in-repo V1.1 State Ledger。
7. 查询 Git 和 GitHub CURRENT。
8. 读取 Authority Manifest，重算所有 SHA-256。

### 10.2 新 worktree admission

执行时重新查询 remote main，不直接复用本文的 02c5b874。记录：

- admitted_base_sha
- admitted_base_tree
- remote branch existence
- open PRs
- exact checks
- authority version/hashes

建议 worktree：

    D:\V3OpenSource-worktrees\v1-1-usable-research-product-01

只有同时满足以下条件才允许创建分支：

- workspace root 与目标 worktree 完全一致。
- 目标 worktree 不存在，或存在但已证明属于同一 branch/lineage。
- GitHub 上计划 branch 不存在；若已存在，先确认它就是同一任务，不得覆盖。
- worktree 基于执行时 fresh origin/main。
- worktree git status 为 clean。
- authority hashes 全匹配。

如果 remote main 在 admission 后漂移：

- 不 rebase。
- 不自动把新 main 混入。
- 在 Ledger 记录 drift，STOP_FOR_REVIEW。

### 10.3 首个仓库内文件

在任何生产代码编辑前创建：

- docs/release/V1_1_USABLE_RESEARCH_PRODUCT.md：本计划的仓库内执行副本。
- docs/release/V1_1_USABLE_RESEARCH_PRODUCT_STATE_LEDGER.md：持续真值源。

Ledger 的前三个一级标题必须按此顺序：

1. TASK_GOAL
2. TASK_PROGRESS
3. PROJECT_AUTHORITY

TASK_PROGRESS 每次必须包含：

- current_checkpoint
- last_completed_action
- exact_next_action
- files_currently_modified
- last_validation_command
- last_validation_result
- admitted_base_sha
- current_head_sha
- remote_head_sha
- open_pr_number/state
- known blockers

## 11. Checkpoint 1 — Product Shell + Runtime Truth

目标：先消除“项目切换错、控制响应串线、界面假操作”，并把长任务的接收与执行解耦。C1 结束后产品仍未提供完整研究，但任何可点击入口都必须真实或 disabled。

### 11.1 先写 characterization tests

在不改行为前固定以下现状：

- Binding persist 发生在 restart/restore 前。
- restoreSession 异常被吞掉。
- A 项目的 lastResearch 可影响切到 B 后的 refresh。
- health timeout 后 slot 仍占用。
- late control frame 没有 generation fence。
- submitResearch 在 response 前完成 provider/pipeline。
- cancelTask 只写状态，未控制计算。
- RequestRouter seen cache 无上限。

这些测试先红或明确标记 EXPECTED_FAILURE；不得用删除断言让它们“通过”。

### 11.2 Correlated control protocol

实施 ControlEnvelopeV1：

- Python RuntimeSession 校验 closed shape 和 generation。
- TypeScript BackendSupervisor 用 pending Map 按 control_request_id 匹配。
- health、shutdown、Product Entry 都走同一 correlated helper。
- late/mismatch frames 进入 bounded diagnostic ring，不进入新 request。
- timeout 清 slot。

标准 ASL request 也记录 runtime_generation；旧 generation response 不能进入 bridge。

### 11.3 真实进程退出闭环

扩展 BackendProcess interface：

- terminate
- kill
- waitForExit(deadline)
- isAlive

restart 顺序：

1. prepareShutdown correlated ack。
2. commitShutdown correlated ack。
3. 等待 exit。
4. 超时 terminate。
5. 再超时 kill。
6. 再次等待并确认 PID 已退出。
7. 只有确认 exit 后才能启动下一 generation 和重新打开同一 SQLite。

旧进程未退出时返回 BACKEND_EXIT_NOT_CONFIRMED，禁止启动新进程。

### 11.4 原子 project activation

按 BindingActivationV2 实施。

Renderer store 新增单一 activateProjectScope action。该 action 原子清空：

- lastResearch
- selectedTask/result/artifact
- run specs/pages
- submit/import outcomes
- recovered task
- in-flight progress/error
- task event cursor
- view selections derived from old project

每个 async action 捕获 scope token，完成前复核。项目 A 的延迟 response 到达 B 时必须丢弃。

禁止只写 lastResearch = null 作为修复。

### 11.5 Product Task Coordinator

复用已有 TaskSupervisor、WorkerSupervisor、lease/resource abstractions，新增 production composition；不要再创建第二套 Task 状态机。

最小生产 worker：

- backend 主 runtime 只 durable accept Task 并快速返回 QUEUED。
- actual provider、factor、backtest 在 child process。
- child 有独立 stdin/stdout pipes，不污染 backend framing。
- heartbeat 2 秒，lease 10 秒。
- worker response 使用现有 typed worker protocol，并补 phase/progress work units。
- 每个 worker 使用独立 SQLite connection/UoW。
- main runtime event loop 在 Task 运行时仍能响应 health、getTask 和 cancel。

C1 只需要把一个 deterministic long-running test operation 接到真实 worker，用它证明 enqueue、health、cancel、deadline、restart reconciliation。研究业务在 C2 接入。

checkpoint/resume 在 C1 保持 NOT_AVAILABLE。中断任务在重启时进入 FAILED / WORKER_LOST / RUNTIME_RESTART_RECONCILIATION，并可按相同 immutable inputs 从头 retry。

### 11.6 Router 与错误边界

- RequestRouter bounded LRU/TTL。
- deadline enforcement。
- product orchestration 只捕获 Exception。
- KeyboardInterrupt/SystemExit 不进入普通 Task error classifier。
- 未识别程序异常分类为 INTERNAL_ERROR / retryable=false；不得伪装成 PROVIDER_TEMPORARY。
- String(value ?? "") 适配改为 typed validator；contract drift fail closed。

### 11.7 分页和 BindingStore

虽然极端 pagination 不是最高产品 blocker，但修复与 project state 同 owner，应在 C1 完成：

- listProjects、listTasks、listBacktestRunSpecs 使用 opaque keyset cursor。
- cursor 绑定 project/filter/sort fingerprint。
- bridge 暴露 loadNextPage，不再内部固定页数 auto-loop。
- page_size 1..100。
- renderer 列表 virtualized，清晰显示还有更多。
- BindingStore 只忽略 ENOENT。

Workspace persisted JSON 增加 maxLength/maxItems；旧文件迁移必须有版本、备份和回滚，不能直接截断用户状态。

### 11.8 Product-mode UI truth recovery

主导航固定为：

- 首页 / 项目
- 数据
- 研究
- 回测
- 结果

Model、Agent、复杂 Canvas 放到 Experimental developer-only 入口；release build 默认不可见。

Home 只显示真实 project-scoped read model：

- 当前项目
- 数据状态
- 最近研究
- 最近回测
- Provider 状态
- 下一步可执行动作

对于尚未在 C2/C3 接通的动作：

- disabled
- 显示 NOT_AVAILABLE 与 reason
- 不允许 React-only success

生产 bundle 不得包含或展示：

- BT-DEMO-021
- demo-v13
- demo universe/strategy
- fixture price/IC/return

开发 fixture 使用独立 dev-only import path。新增 release bundle scan，发现 demo token 即失败。

### 11.9 C1 migration

0005 migration 的 C1 部分至少增加：

- task.execution_deadline_at
- task_output
- publication_intent 基础表
- session immutable project-binding trigger/constraint
- 必要的 cursor indexes

Migration 要求：

- additive only
- transactionally applied
- backup before migration
- old V1 catalog upgrade test
- schema_version 精确检查
- downgrade 不承诺；失败必须保留原 DB 和备份

### 11.10 C1 验收

ACC-C1-01 Binding failure matrix：

- candidate start fail
- restore fail
- binding rename fail
- crash before rename
- crash after rename

每个场景都断言 active binding、backend generation、session 和 renderer scope 一致。

ACC-C1-02 Project isolation：

- Project A 完成 research state。
- 人为延迟 A 的 Task/Result response。
- 切换 Project B。
- A response 到达。
- B UI 中不存在任何 A task/result/artifact/token。

ACC-C1-03 Health timeout recovery：

- 第一次 health 超时。
- 第二次 health 立即可发。
- 第一次 late reply 被丢弃。
- pending/tombstone 数量不超过上限。

ACC-C1-04 Exit fencing：

- child backend 忽略 graceful shutdown。
- supervisor terminate/kill 并 wait。
- 未确认 exit 前无新 generation。

ACC-C1-05 Real cancellation：

- Task 返回 QUEUED 的 response 在 2 秒内完成。
- worker 继续运行时 health/getTask 可响应。
- cancel 后 child 确实停止，Attempt 最终 CANCELLED。
- 不能只检查数据库 state。

ACC-C1-06 Deadline：

- pre-dispatch expired request 被拒。
- running Task 到期被 cooperative cancel 后升级终止。
- late worker terminal 不可把 cancelled Task 变成 success。

ACC-C1-07 Bounded memory：

- 发送超过 4096 个 request。
- seen cache/tickets/control pending 均保持上限。

ACC-C1-08 UI truth：

- PRODUCT build 扫描无 demo token。
- 所有尚未连接按钮 disabled + reason。
- Home 只呈现当前 project 的真实 read model。

C1 required commands：

- npm.cmd run validate:authority
- npm.cmd run typecheck
- npm.cmd run lint
- npm.cmd run test:unit
- npm.cmd run test:backend
- npm.cmd run build
- npm.cmd run test:runtime
- 新增的 C1 fault-injection test command

只有 ACC-C1-01 至 08 全部 PASS 才可创建 checkpoint 1 commit。

## 12. Checkpoint 2 — Data + Factor Research

目标：形成真实 Data → Snapshot → Universe → Factor → Evaluation 纵切，并让 Golden Case A/B 都有符合统计语义的产品结果。

### 12.1 Provider acquisition

把 provider capture 从 Task acceptance 前移动到 worker 内。正确顺序：

1. 校验 closed intent 与资源 bounds。
2. durable create Task/Run/Attempt/context artifact。
3. 返回 QUEUED。
4. worker 执行 provider capture。
5. 只有实际 bytes 成功且 hash/normalization 验证后才创建 RawCapture/Snapshot。

保留 AKShare adapter 的优点：

- provider refs 由 backend 所有。
- raw bytes、request fingerprint、connector version、acquisition time 都进入 provenance。
- provider unavailable 时 canonical_chain_created=false。
- fallback_used=false。

扩展 provider intent：

- single symbol profile：1 个 symbol。
- explicit Universe profile：1..50 个 symbol，concurrency=2。
- date range：不再固定 31 天，但总 sessions/bytes 受资源 admission。
- 每个 symbol capture 都有独立 raw identity。
- 全 Universe snapshot 默认 ALL_OR_NOTHING；任一 symbol acquisition/normalization fail 时，不发布完整 snapshot。

禁止 automatic fallback。UI 的 Retry、Change data source、Import local data 是三个新的用户动作和新的 request hash，不是同一 Task 的暗中替代。

### 12.2 Local CSV/Parquet

实现 LocalDataImportIntentV1。

CSV 和 Parquet 都先生成：

- RawFileArtifact
- ImportSchemaMappingArtifact
- NormalizationReceipt
- CanonicalEodPartitionArtifact
- DataSnapshot candidate

Snapshot publish 前运行：

- closed schema validation
- unit normalization
- duplicate/gap diagnostics
- OHLC invariants
- date ordering
- symbol/instrument resolution
- row/symbol/session limits
- hash repeatability

Local source没有 provider available-time/revision authority时：

- truth admission 仍为 PRE_ALPHA。
- UI 显示 LOCAL_USER_SUPPLIED / PIT_UNPROVABLE。
- 不因“本地文件”而升级 formal truth。

Parquet dependency 若新增：

- exact pin
- SBOM 更新
- Windows packaged inclusion
- clean-machine import proof
- package size delta 记录
- 不允许 runtime pip install

### 12.3 Data Workspace

页面必须显示：

- 当前 DataSource
- source type：AKShare 或 Local Import
- symbol/Universe
- date coverage
- rows/instruments
- volume/amount units
- adjustment state
- last acquisition/import
- raw_capture_id
- snapshot_id
- quality status
- PIT/revision/calendar/status capability reasons

只有以下动作可点击：

- 从 AKShare 获取
- 导入 CSV
- 导入 Parquet
- 创建静态 Universe
- 打开 Snapshot/diagnostics

未实现的 index/industry/concept/dynamic Universe 均 disabled / NOT_AVAILABLE。

### 12.4 Static Universe owner

V1.1 只交付 USER_DEFINED_STATIC Universe：

- user 提供 symbol list。
- 后端通过 instrument alias owner 解析。
- membership artifact 显式列出每个 instrument。
- membership version 绑定 snapshot、as_of、knowledge_cutoff 和 truth ceiling。
- 未在 snapshot 中出现的 symbol 默认 fail closed；不能静默丢弃。
- Case A 是 1-member Universe。
- Case B 是至少 20-member Universe。

### 12.5 Factor authoring 与 TDX translation

Factor Workbench 的按钮必须调用 backend application service：

    Create Draft
    → Parse
    → Static Analyze
    → Validate DataSemantics
    → Publish FactorDefinitionVersion
    → Enqueue Materialization
    → Enqueue Analysis
    → Persist Read Model

复用：

- TdxParser
- TdxTranslator
- FormulaDocumentVersion
- FactorDefinitionVersion
- DeterministicReferenceEvaluator
- FeatureMaterialization
- FactorEvaluation

新增 panel evaluator 处理 symbol/date 轴，不修改旧 registry 对已有 factor hash 的解释。

Golden formula 必须直接使用用户输入文本，不允许 renderer 根据字符串匹配返回硬编码 fixture。

### 12.6 MJ 单位真值

MJ 的正确性 gate：

1. 数据 profile 明确 canonical volume unit。
2. 如果 source volume 是 SHARES，则 TDX VOL 映射为 HANDS 时乘 0.01。
3. 如果 source volume 已是 HANDS，则 multiplier 为 1。
4. MJ = AMOUNT / VOL / 100 后必须得到 CNY_PER_SHARE。
5. volume 为 0/null 时结果为 explicit null + DIVIDE_BY_ZERO_OR_MISSING，不得 Infinity/NaN/0。

AKShare 成交量单位在 connector admission artifact 中必须有版本化证据；未能证明单位时 MJ 为 DATA_SEMANTICS_UNRESOLVED，不能运行。

### 12.7 因子 materialization

worker 按 instrument partition 计算时间序列：

- 输入先按 instrument、date 排序。
- 每个 instrument 独立 warmup。
- rolling operator 不跨 symbol。
- 每个输出行保留 source partition/hash 和 factor_version_id。
- checkpoint 仅可选地落在完整 instrument partition 边界；V1.1 UI 不承诺 resume。
- large output 以 admitted Parquet 或 canonical chunk artifacts 存储；read model 只含摘要和 stream refs。

Golden overlay：

- K 线来自同一 snapshot。
- MA/MJ/signal 来自同一 factor materialization。
- chart x-axis 用相同 calendar/session dates。
- 任一 hash/snapshot mismatch 时拒绝 overlay。

### 12.8 横截面评价

新增 FactorAnalysis application service，按 FactorAnalysisSpecV1：

1. 对每个 t 建立 exact Universe membership。
2. 连接 factor value at t。
3. 连接 forward return t→t+5。
4. 过滤 missing，但 coverage 分母保持原 membership。
5. 每日计算 IC/RankIC/quantiles。
6. 聚合 IC mean/std/ICIR、yearly distribution。
7. 生成 diagnostics，包括 excluded reason counts。
8. 写 content-addressed analysis artifact 和 project-scoped read model。

五分位 tie policy：

- 按 factor value、instrument_id 稳定排序。
- bucket size 尽量均衡，前 remainder buckets 多一个。
- 相同 factor 值跨 bucket 时记录 TIE_SPLIT_BY_STABLE_ID。
- 若业务不接受 tie split，可选择整组拒绝；V1.1 默认稳定切分并透明记录。

Turnover：

- 以相邻评价日 top quantile membership 的 one-way change 计算。
- 第一个有效日为 NOT_AVAILABLE / NO_PRIOR_PORTFOLIO，而不是 0。

Long-short spread：

- upper quantile mean forward return - lower quantile mean forward return。
- 明确是 research diagnostic，不是可交易策略结果。

### 12.9 Factor Research UI

Research 页面中心是图表，不是卡片墙：

- 顶部：project/snapshot/universe/factor context。
- 主区：K 线 + factor overlay + signal markers。
- 下区 tab：Factor values、IC series、Quantile returns、Diagnostics、Lineage。
- 右侧 inspector：参数、units、truth、refs、hash。

状态必须覆盖：

- EMPTY
- LOADING
- QUEUED
- RUNNING
- PERSISTING
- SUCCESS
- ERROR
- UNAVAILABLE
- DISCONNECTED
- INSUFFICIENT_SAMPLE

任何大表都从 artifact stream 分页/分块读取，不能把全表塞进 workspace JSON。

### 12.10 Research Copilot

C2 可接一个 L1_DRAFT-only Research Copilot，但不是 blocker。

允许：

- 用户描述因子。
- AI 生成 TDX/Factor draft。
- 展示模型 provider/response ID、prompt hash、token usage（若 provider返回）、工具 trace。
- 用户明确 review 后送 DSL validator。

禁止：

- AI 直接 publish FactorDefinition。
- AI 自动运行 Task。
- AI 伪造 validation 或 result。
- provider 不可用时用固定 draft 冒充模型输出。

若预算/receipt 无法闭合，Copilot 在 V1.1 保持 NOT_AVAILABLE，不阻止核心研究链。

### 12.11 C2 验收

ACC-C2-01 Secure import：

- oversized CSV/Parquet
- symlink/reparse point
- file replacement race
- nested Parquet
- duplicate key
- invalid OHLC
- unknown columns
- invalid UTF-8

全部 fail closed，且没有 published Snapshot。

ACC-C2-02 CSV/Parquet equivalence：

- 两个格式表达同一数据。
- normalized payload hash、Snapshot semantic identity 和 factor outputs 完全相同。

ACC-C2-03 Unit equivalence：

- 一份 volume=SHARES，一份等价 volume=HANDS。
- 显式 profile 转换后 MJ 值逐行相同。
- 不声明单位时被拒绝。

ACC-C2-04 Provider failure：

- provider 抛 dependency/network/schema error。
- Task FAILED，reason 精确。
- fallback_used=false。
- canonical_chain_created=false。
- 不存在伪造 bars/snapshot。

ACC-C2-05 Golden TDX：

- 真实 parser 解析 MJ、MA5/20/60、GOLDEN_CROSS、DEATH_CROSS。
- 与独立手算 fixture 每个值/None/cross date 一致。
- 同 inputs 重跑得到相同 IDs/hashes。

ACC-C2-06 Axis safety：

- 两个 symbols 的 rolling window 不串线。
- RANK 只在同 date 横截面。
- LEAD/negative lag 被拒。
- t 的 factor 不读取 t+1。

ACC-C2-07 Single-symbol honesty：

- 600519 overlay 可用。
- IC/RankIC/quantile 返回 INSUFFICIENT_SAMPLE。
- UI 不渲染数值图。

ACC-C2-08 Cross-sectional metrics：

- 至少 20 symbols × 25 evaluable dates 的已知小数据集。
- 每日 IC/RankIC、五分位、aggregate mean/std/ICIR 与独立参考计算一致。
- missing、constant、tie、no-prior turnover 分支有断言。

ACC-C2-09 Persistence：

- 关闭 backend/Electron。
- 用同一 userData/storage 重启。
- project、source、snapshot、universe、formula、factor、analysis 全部从 canonical IDs 恢复。
- 不需要重新导入或重新计算。

ACC-C2-10 Product UI：

- PRODUCT mode 无 fixture。
- Data/Research 的所有 enabled action 都产生真实 backend request、Task 和 canonical readback。
- 用户不需要输入 project_id、snapshot_id 或 artifact_id；这些只在 inspector 展示。

C2 required commands：

- C1 全部 required commands
- 新增 local-data security tests
- 新增 TDX/panel evaluator property tests
- 新增 factor-analysis golden tests
- npm.cmd run smoke:product-data
- npm.cmd run smoke:product-factor
- npm.cmd run smoke:frontend

Live provider acceptance 在网络真实可用时运行；失败不得换 fixture 通过。Ledger 记录 PASS、FAIL 或 NOT_RUN。

只有 ACC-C2-01 至 10 全部 PASS，且 live provider gate 没有被错误升级，才可创建 checkpoint 2 commit。

## 13. Product Entry 1.1 加法式 operation policy

不得改变现有 1.0 wire shape 或重新解释已有 operation。为 V1.1 产品纵切新增 version 1.1.0 operations：

- ProductEntryService.v1.importLocalDataset
- ProductEntryService.v1.submitFactorStudy
- ProductEntryService.v1.publishResearchStrategy
- ProductEntryService.v1.submitResearchBacktest
- ProductEntryService.v1.getProjectHome

共同规则：

- expected_api_version：1.1
- command 都先 durable accept，再返回 QUEUED。
- command read model 必含 maturity=PRODUCT_CONNECTED、truth=NOT_FORMAL、admission=PRE_ALPHA。
- checkpoint_resume=UNAVAILABLE。
- retry=NEW_ATTEMPT_SAME_RUN_FROM_START。
- numeric truth 仍委托 canonical owner；ProductEntry 只负责 orchestration。
- 大 payload 只传 immutable refs，不传 bars、factor values、weights 或 results。

旧 ProductEntryService.v1.submitResearch 保持 1.0 compatibility 和单 symbol bounded profile；V1.1 UI 不把它当完整 Factor Research。

若代码生成/contract fixture 规则要求新的 contract source，先更新唯一 contract seed/source，再生成 Python/TypeScript/fixture；禁止手工改一侧造成 drift。

## 14. Checkpoint 3 — Strategy + Backtest + Final Result

目标：把真实 Factor/Signal 接到 canonical Strategy、Portfolio、Risk、Backtest 与 Result owner，关闭 Result finality，并让所有结果页面只读真实 VALID Result。

### 14.1 Strategy authoring

Strategy 页面从 ResearchStrategySpecV1 表单开始，不把 ReactFlow 当 V1.1 主入口。

用户流程：

1. 选择已发布 UniverseVersion。
2. 选择 entry/exit boolean FactorVersion。
3. 选择 position sizing、max positions、gross exposure。
4. 选择 cost/execution/assumption profiles。
5. Validate。
6. 查看编译预览。
7. 用户确认 Publish。

Backend：

- 验证所有 refs 同 project、同 snapshot/calendar/knowledge context。
- 编译为现有 StrategyIr/StrategyDefinition owner 可接受的 closed IR。
- materialize Signal artifact。
- 由 Portfolio owner 产生 TargetWeight。
- 由 RiskPolicy owner验证/调整。
- 每个 owner 输出 immutable ID/hash/ref。

禁止：

- renderer 直接给最终 weights。
- Strategy UI 只存 Zustand 然后显示成功。
- 用 demo-v8 或 visual node fixture 代替 backend compile。

Golden single-symbol state machine：

- GOLDEN_CROSS at close t：目标从 0 变 1。
- DEATH_CROSS at close t：目标从 1 变 0。
- execution effective time：next admitted open。
- 重复 entry while long 和重复 exit while flat 为 no-op，并进入 diagnostic。

### 14.2 Research backtest preflight

submitResearchBacktest 在 durable Task acceptance 前只做轻量、无副作用 preflight：

- refs 存在并属于 project。
- immutable hashes 格式正确。
- session/instrument/product bounds。
- requested date range 在 data coverage 内。
- requested date range 在 rule/cost/execution policy coverage 内且无 gap。
- unsupported corporate actions 已知时拒绝。
- selected assumption profile 明确。

大数据 resolve、RunSpec materialization 和 engine run 在 worker 中进行。

ResearchBacktestRunSpec 必含：

- snapshot/universe/factor/strategy/signal exact refs
- portfolio/target/risk exact refs
- rule/cost/execution/assumption profile exact refs
- calendar ref
- initial cash/holdings
- resource admission receipt
- engine/runtime/environment version
- truth propagation receipt

### 14.3 Backtest engine 修复

在现有 DeterministicAshareBacktestEngine 上做最小、可测试扩展；不要另写第二引擎。

必做：

- 初始持仓未来日期拒绝。
- affordability 从逐 lot decrement 改为 O(log lots)。
- slippage policy 纳入 execution price、cost、fill 和 content hash。
- volume participation cap 产生真实 partial fills。
- requested、eligible、filled、unfilled quantity 全部进入 diagnostics。
- unknown trading state 根据 STRICT/APPROXIMATE profile 处理。
- caller flags 不直接成为 authority；worker 从 snapshot + ExecutionPolicy owner resolve typed DailyMarketState。
- session open/close、calendar 和 signal availability 对齐。
- same-bar lookahead 测试。
- no price/invalid price fail closed。
- unsupported corporate actions 在 preflight 拒绝。

保留并回归：

- sell before buy ordering
- T+1
- lot rules
- explicit fees
- cash/position ledgers
- raw close fail-closed NAV
- deterministic content-addressed result

执行结果必须记录：

- order reason
- blocking reason
- requested/fill/unfilled
- raw reference price
- slippage-adjusted execution price
- participation cap
- all fee components
- assumption reason

### 14.4 Execution policy coverage

新增 ExecutionPolicyRegistry：

- policy versions effective ranges 不重叠。
- requested run range 必须完整覆盖。
- main board/STAR/ChiNext/BSE 和 ST/IPO 特殊规则只有在有版本化 evidence 时才 admitted。
- 缺 evidence 的 board/date 组合返回 EXECUTION_POLICY_COVERAGE_UNAVAILABLE。
- 不从最近 policy 向历史或未来外推。

V1.1 release note 必须列出实际 admitted board/date matrix。没有证据的格子为 NOT_AVAILABLE。

### 14.5 Result publication 与 reconciliation

用 PublicationIntentV1 替换 ProductArtifactBatch + 分散 Result insert 的产品路径。

旧 helper 可保留给已验证兼容场景，但 V1.1 research/backtest outputs 必须走新 saga。

Result state：

- PENDING_RECONCILIATION
- VALID
- INVALID

Task state：

- engine 完成时仍为 RUNNING/PUBLISHING。
- Result VALID 与 analytics/reference/task_output 同一 Catalog transaction 后才 SUCCEEDED。
- Result INVALID 时 Task FAILED。

实现并绑定：

- ResultService.v1.reconcileLedger
- ResultService.v1.finalizeResult
- ResultService.v1.getResult
- ResultService.v1.compareResults（若比较 read model 可在 C3 有界完成，否则 capability 明确 UNAVAILABLE）

getResult section 支持：

- summary
- analytics
- orders
- fills
- positions
- diagnostics
- lineage

大表 section 返回 stream ref + row count/page metadata；不内嵌全部 rows。

### 14.6 Result analytics

复用 DeterministicResultAnalyticsEngine 已有真实实现：

- total return
- annualized return
- annualized volatility
- Sharpe
- Sortino
- max drawdown/episode
- monthly/yearly returns
- costs
- turnover
- optional benchmark

V1.1 增加：

- Calmar：annualized_return / abs(max_drawdown)，zero drawdown 时 NOT_AVAILABLE。
- gross/net exposure time series。
- position concentration summary。
- trade/order/diagnostic tables。
- Factor → Signal → TargetWeight → Order → Fill → Result lineage refs。

Benchmark：

- 只有 exact-date-aligned、带来源/hash 的 BenchmarkSeries 才 AVAILABLE。
- 没有 benchmark 时 status=BENCHMARK_NOT_AVAILABLE。
- 不得用 0 或策略自身曲线冒充 benchmark。

Analytics artifact 必须绑定：

- source Result ID/hash
- analytics policy ID/hash
- benchmark ID/hash 或 explicit null
- engine version
- truth ceiling

### 14.7 Real artifact stream/export

C3 接通 Result charts/tables 所需 stream consume；完成 project reachability、one-use/expiry/generation fence 和 hash verification。

接通用户 Export Result：

- 可选 summary JSON、orders CSV、fills CSV、analytics JSON。
- 输出内容从 VALID Result refs 生成。
- Electron 真实写目标文件。
- export Task 在文件落盘/hash 校验前不成功。
- export manifest role 与 experiment expansion role 分开。

### 14.8 Task feedback

统一 Task status component：

- QUEUED
- ACQUIRING
- VALIDATING
- COMPUTING
- PUBLISHING
- RECONCILING
- COMPLETE

只在 worker报告有界 work units 时显示百分比；否则显示阶段和已完成单位，不显示假 73%。

失败映射为用户可行动信息：

- PROVIDER_ACQUISITION_UNAVAILABLE
- DATA_SEMANTICS_UNRESOLVED
- INSUFFICIENT_SAMPLE
- EXECUTION_POLICY_COVERAGE_UNAVAILABLE
- CORPORATE_ACTION_NOT_AVAILABLE
- RESOURCE_REJECTED
- RESIDUAL_VALIDATION_FAILED
- BACKEND_DISCONNECTED

按钮：

- Retry from start（只在 retry policy 允许时）
- Change data source
- Import local data
- View details
- Open valid result

Result 非 VALID 时不显示 Open valid result。

### 14.9 Strategy/Backtest/Result UI

Backtest 页面：

- 当前 StrategyVersion、Snapshot、Universe、policy coverage。
- 明确 start/end allowed range。
- initial cash。
- commission/slippage/participation。
- STRICT/APPROXIMATE profile。
- resource estimate。
- Run 按钮只在 preflight PASS 时 enabled。

Results 页面：

- 默认打开最近 VALID Result。
- summary metrics 保持数值状态类型。
- equity/drawdown/exposure chart。
- orders/fills/costs/positions tables。
- monthly/yearly returns。
- lineage inspector。
- PENDING/INVALID 单独呈现，不混进 valid comparison。

旧 demo Backtest panel、fixed metrics、fixture ResultAnalytics 在 PRODUCT build 删除或 dev-only 隔离。

### 14.10 C3 验收

ACC-C3-01 Async contract：

- submitResearchBacktest 在 2 秒内返回 durable QUEUED。
- worker 运行期间 health/getTask/getEvents 可用。
- accepted Task 在 provider/engine 前已存在。

ACC-C3-02 Signal timing：

- 人工构造 t close 发生 Golden Cross。
- t open 无交易。
- t+1 admitted open 才生成 order/fill。
- Death Cross 同理。

ACC-C3-03 Fill realism：

- volume cap 导致 partial fill。
- slippage 对 buy/sell 方向正确。
- cash constraint 始终 cash >= 0。
- affordability 在超大 requested lots 下保持 O(log n) 测试预算。

ACC-C3-04 Rule truth：

- STRICT + unknown state 阻止订单。
- APPROXIMATE 允许时生成 AssumptionReceipt 且结果 badge 为 APPROXIMATE。
- caller 篡改 boolean flag 不能越过 resolver。

ACC-C3-05 Initial holding：

- acquired_on > first session 在 RunSpec create/preflight 被拒。
- T+1 sellable quantity 与合法历史日期一致。

ACC-C3-06 Corporate actions：

- cash dividend。
- integral bonus/split。
- fractional、rights、delisting/unknown action preflight fail。
- 不存在 silent ignore。

ACC-C3-07 Publication crash matrix：

在以下点注入进程崩溃：

- intent committed 前
- STAGED 后
- bytes publish 后、Catalog commit 前
- Catalog commit 后、reconcile 前
- reconcile artifact 后、Result finalize 前
- Result finalize transaction 中

重启后每个 intent 只能恢复为唯一 FINALIZED 或 FAILED；不得有 Task SUCCEEDED + Result 非 VALID。

ACC-C3-08 Reconciliation corruption：

- 篡改 ledger sequence、cash balance、fee link、position balance、NAV。
- Result INVALID。
- Task FAILED / RESIDUAL_VALIDATION_FAILED。
- UI 不显示为完成结果。

ACC-C3-09 Stream security：

- 跨 project artifact ID。
- expired ticket。
- replay consumed ticket。
- wrong generation。
- wrong chunk hash。

全部拒绝；正常 large artifact 逐 chunk 重组后的 hash 等于 descriptor。

ACC-C3-10 Export truth：

- 用户选择目标。
- 实际文件存在，hash/size 等于 manifest。
- 中途失败只留下可识别 tmp，Task FAILED。
- 用户取消为 NOT_RUN。

ACC-C3-11 Analytics golden：

- 使用独立手算 NAV/fees/fills fixture。
- return、annualization、volatility、Sharpe、Sortino、drawdown、Calmar、turnover、monthly/yearly、exposure 一致。
- insufficient sample、zero variance、no benchmark 显式状态一致。

ACC-C3-12 Result lineage：

- 从 Result 可到 Factor、Signal、TargetWeight、RiskPolicy、Order、Fill、Snapshot、RawCapture。
- 每条 ref 同 project 且 hash 可重验。

ACC-C3-13 Restart：

- completed VALID Result 在 Electron/backend 重启后恢复。
- charts/tables 从 canonical read model/artifacts 重建。
- 不运行计算、不使用旧 renderer cache。

C3 required commands：

- C1/C2 全部 required commands
- backtest golden/property tests
- publication fault-injection suite
- Result reconciliation/analytics tests
- artifact stream/export tests
- npm.cmd run smoke:product-backtest
- npm.cmd run smoke:product-result
- npm.cmd run smoke:product-runtime
- npm.cmd run smoke:electron:runtime

只有 ACC-C3-01 至 13 全部 PASS 才可创建 checkpoint 3 commit。

## 15. Checkpoint 4 — Usability + Release Qualification

目标：把已经真实接通的纵切变成可安装、可理解、可恢复、可独立审查的 Windows 产品候选。

### 15.1 统一信息架构

一级导航保持五项：

- 首页 / 项目
- 数据
- 研究
- 回测
- 结果

页面职责：

首页 / 项目：

- 创建、打开、切换项目。
- project binding 与 backend health。
- 最近数据、研究、回测、结果。
- 下一步 action。

数据：

- provider/local acquisition。
- source units/capabilities。
- Snapshot/Universe。
- quality/provenance。

研究：

- formula editor。
- factor overlay。
- factor evaluation。
- diagnostics/lineage。

回测：

- bounded strategy form。
- execution/cost/risk assumptions。
- preflight/resource estimate。
- Task progress。

结果：

- VALID results。
- analytics/tables。
- compare/export。
- lineage。

Advanced Model/Agent/System：

- Experimental flag 下才可见。
- release acceptance 不访问。
- 没有真实 wiring 的 action disabled。

### 15.2 视觉与交互 gate

必须测试：

- 1366×768
- 1440×900
- 1920×1080
- 2560×1440
- Windows scaling 100%、125%、150%

每页检查：

- overflow/clipping
- minimum panel sizes
- Dockview resize
- ECharts resize
- Monaco resize
- inspector/bottom drawer collision
- keyboard focus order
- visible focus
- zoom/scaling
- empty/loading/error/unavailable/disconnected

字体：

- body >= 13px
- 重要 table >= 12px
- 11–12px 只用于 metadata

产品 doctrine：

- Chinese-first。
- low chrome / no card wall。
- developer IDs 不作 primary label。
- trace-critical token 在 inspector 精确显示并可复制。
- 不用颜色单独表达状态。

### 15.3 Golden User Journey A

在全新安装和空 userData 上：

1. 安装并启动。
2. 创建“我的第一个量化项目”。
3. 通过 AKShare 获取 600519，或用户明确选择本地导入；两条路径不互相伪装。
4. 看到真实 K 线和 source/provenance。
5. 输入 Golden formula。
6. backend parse/validate/publish/materialize。
7. 看到 MJ、MA5/20/60、金叉/死叉 overlay。
8. IC 区域明确显示单标的样本不足。
9. 创建 long-only entry/exit Strategy。
10. 选择成本、滑点、参与率和 assumption profile。
11. 运行 research backtest。
12. 看到 VALID Result、曲线、回撤、订单、成交、费用、持仓和 lineage。
13. 保存并退出。
14. 重启。
15. 原项目、数据、公式、因子、策略、Result 全部恢复。

全过程：

- NO demo data
- NO fake action
- NO implicit provider fallback
- NO source code
- NO developer ID as primary UX
- NO unexplained blank screen/spinner

### 15.4 Golden User Journey B

在同一或新项目：

1. 导入至少 20 symbols、满足 20 个评价日的 CSV/Parquet。
2. 明确 volume unit。
3. 发布 Snapshot 和 static Universe。
4. 创建数值 factor。
5. 运行 Factor Analysis。
6. 查看每日 IC/RankIC、IC mean/std/ICIR、五分位、spread、coverage/missing、turnover、yearly distribution。
7. 随机抽取日期与独立参考计算核对。
8. 退出重启后结果不重算即可恢复。

### 15.5 统一 CI product gate

拆成可诊断、但共同 required 的 jobs：

Job A — authority-contract-quality（Ubuntu）：

- full history checkout，fetch-depth=0。
- authority validator。
- contract fixtures/codegen drift。
- typecheck/lint。
- Ruff/Pyright 或仓库批准的等价 Python静态检查。
- unit/property tests。

Job B — backend-runtime（Ubuntu）：

- exact Python version。
- hash-locked dependencies 若本 PR能有界完成；否则记录 Deferred Gap，不伪称 hermetic。
- backend tests。
- worker cancel/deadline。
- publication fault injection。
- factor/backtest/result golden tests。

Job C — windows-product-integration：

- Windows latest。
- npm.cmd ci。
- packaged Python deps at build time。
- build。
- Electron runtime tests。
- product data/factor/backtest/result smokes。
- PRODUCT bundle fixture scan。
- persistence/restart。

Job D/E — Windows package + clean machine：

- Job D exact PR head build installer/unpacked package。
- 上传 package/hash/evidence driver。
- Job E 不 checkout，无 source tree、无 node_modules、无 npm/pip install。
- 只下载 Job D artifact。
- 安装并执行 Golden local-import journey。
- 重启并复核 persistence。
- 记录 installer/package/manifest/evidence hashes。

Job F — live provider acceptance：

- exact candidate head/package。
- 实际 AKShare capture。
- 无 fixture/fallback。
- 外部不可用时 FAIL 或 BLOCKED_PROVIDER_ACCEPTANCE；不得转换 PASS。

Workflow actions：

- 从可漂移 major tag 改为审核后的 exact commit SHA。
- 记录 action SHA source。

Required product gate 是 A 到 F 的组合状态。若 repository settings 尚未配置 required checks/required review，则 release 状态为 PENDING_EXTERNAL_REPO_ADMIN。

### 15.6 Clean-machine truth

Job E 必须证明：

- workspace 开始时无 .git、源码、package manifests、node_modules。
- 无 checkout action。
- 无 npm/pip install。
- userData/storage 在 install root 外。
- package 自带 runtime/dependencies。
- 首次启动、创建项目、导入、研究、回测、结果、退出、重启均由安装产品完成。
- 输出 evidence JSON 带 exact source SHA/tree、package hash、installer hash、runtime build manifest、userData isolation 和每个 acceptance step。

同机源码 smoke 只能称 ISOLATED_SAME_MACHINE，不能替代 clean-machine。

### 15.7 文档 truth reconciliation

在 C4 只更新非 P0 docs，使它们与 exact candidate 一致：

- README：V1.1 产品能力、truth ceiling、安装/Golden journey。
- CURRENT_STATUS：删除过时“desktop/backend 未连接”等陈述。
- PRODUCT_SURFACE：每个 action 的 FORMAL/PRODUCT_CONNECTED/DEMO/UNAVAILABLE。
- V3_DEFERRED_GAPS：关闭项带 evidence，未关闭项保留 literal state。
- V1_0_RELEASE_CANDIDATE：作为历史记录写明最终 merge/CI，而不是保持 PENDING。
- 新 V1_1 release doc：candidate SHA、checks、known limits、admitted date/board matrix。

文档不得把：

- local smoke 写成 hosted clean-machine。
- Result PENDING 写成 final。
- provider success 写成 PIT formal。
- merged head 写成 production release。
- tests PASS 写成用户 journey PASS。

### 15.8 Version 与 package

只有 C4 全部 acceptance 通过后才将 package version 从 1.0.0 更新到 1.1.0。

同步更新：

- package.json/package-lock
- electron-builder artifact names
- build/release manifests
- SBOM
- verification scripts
- clean-machine expected filenames
- docs

若 package dependency 增大，记录：

- installed/unpacked/installer bytes before/after
- startup time
- import peak RSS
- factor/backtest time on fixed dataset

性能 budget：

- cold launch 到可交互 <= 15 秒（clean Windows runner）
- project switch <= 5 秒，不含用户发起的数据计算
- 600519 chart first render <= 5 秒（已缓存 snapshot）
- Golden factor materialization <= 60 秒（固定 acceptance dataset）
- Golden backtest <= 60 秒（固定 admitted period）
- UI 主线程长任务期间无超过 250ms 的不可交互卡顿

超过 budget 为 FAIL；如 runner 噪声需要调整，必须先记录 baseline 和理由，不能静默放宽。

### 15.9 C4 验收

ACC-C4-01 Journey A：全新安装完整 PASS。

ACC-C4-02 Journey B：横截面评价完整 PASS。

ACC-C4-03 Restart：两条 Journey 的 canonical state 重启恢复。

ACC-C4-04 Screen matrix：4 个分辨率 × 3 个 scaling 的关键页面 evidence PASS。

ACC-C4-05 Accessibility baseline：

- keyboard 可完成核心 journey。
- focus visible。
- forms 有 label/error association。
- status 不只依赖颜色。
- charts 有文字摘要/table alternative。

ACC-C4-06 Product truth scan：

- release bundle 无 demo tokens/fixtures。
- enabled actions 有真实 bridge call。
- unavailable capability 有 reason。

ACC-C4-07 Unified CI：Jobs A–F 精确 candidate head 状态按真值记录。

ACC-C4-08 Clean machine：无 checkout/no install Job E PASS。

ACC-C4-09 Package integrity：

- package/installer/SBOM/manifests hashes 一致。
- bundled Python/dependencies exact。
- no source-tree dependency。

ACC-C4-10 Docs：status/release/deferred/product surface 与 candidate/current 一致。

ACC-C4-11 Governance：

- final PR OPEN。
- head SHA 锁定。
- required checks 都是同一 head。
- 至少一个非作者 independent review APPROVED。
- 若无 review，STOP_FOR_INDEPENDENT_REVIEW。

C4 required commands：

- npm.cmd run validate
- npm.cmd run validate:public
- npm.cmd run smoke:product-runtime
- npm.cmd run smoke:product-data
- npm.cmd run smoke:product-factor
- npm.cmd run smoke:product-backtest
- npm.cmd run smoke:product-result
- npm.cmd run package:win:release
- npm.cmd run verify:package
- npm.cmd run verify:release
- npm.cmd run smoke:product-release
- 新的 V1.1 clean-machine driver

不存在的 script 必须在相应 checkpoint 新增并写入 package.json；执行者不能跳过后仍写 PASS。

只有 ACC-C4-01 至 11 全部满足其真实状态才可创建 checkpoint 4 commit。

## 16. 审计问题处置矩阵

处置状态定义：

- CLOSE：V1.1 必须以测试和产品证据关闭。
- DOWNGRADE：撤下或禁用未兑现 capability，保持 NOT_AVAILABLE。
- PARTIAL：关闭 V1.1 产品所需子集，剩余不宣称。
- DEFER：不在 V1.1 实施，必须进入 Deferred Gaps。

| Audit ID | V1.1 处置 | Checkpoint | 退出条件 |
|---|---|---|---|
| P0-01 同步进程执行 | CLOSE/PARTIAL | C1/C3 | isolated worker、真实 cancel/deadline/health responsive；checkpoint/resume 保持 NOT_AVAILABLE |
| P0-02 Product Research 无研究意义 | CLOSE/PARTIAL | C2/C3 | 真实 data/factor/strategy/backtest；单标的与横截面评价分开；formal PIT 仍不宣称 |
| P0-03 Binding 非原子 | CLOSE | C1 | BindingActivationV2 fault matrix |
| P0-04 renderer 跨项目污染 | CLOSE | C1 | ProjectScopeToken + delayed response isolation |
| P0-05 Result finality/跨介质事务 | CLOSE | C3 | durable publication intent、reconciliation、Result VALID before Task success |
| P0-06 Artifact 假闭环 | CLOSE/PARTIAL | C3 | real stream/export；GC execute DOWNGRADE/DEFER |
| P0-07 health 永久占位 | CLOSE | C1 | correlated control + bounded tombstone |
| P0-08 Backtest 执行真实性 | CLOSE/PARTIAL | C3 | research execution semantics闭合；formal BacktestService DOWNGRADE |
| P0-09 CI 非统一产品门禁 | CLOSE | C4 | required Jobs A–F、Windows product + clean machine |
| P0-10 治理冲突 | CLOSE | C4 | independent approval，final STOP_FOR_INDEPENDENT_REVIEW |

### 16.1 Runtime/P1

| Finding | 处置 |
|---|---|
| RequestRouter seen 无界 | C1 CLOSE |
| deadline 只解析 | C1 CLOSE |
| Cancel facade 不停止计算 | C1 CLOSE |
| Resume 不可兑现 | C1 DOWNGRADE；不绑定、不显示 |
| Product Research 捕获 BaseException | C1 CLOSE |
| 未知异常伪装成 adapter/retry | C1 CLOSE |
| Experiment cells 串行 | V1.1 DOWNGRADE；产品入口隐藏，worker DAG DEFER |
| shutdown 无 checkpoint | 明示 UNAVAILABLE；真实 cancel/exit CLOSE |
| terminate 不 wait-for-exit | C1 CLOSE |
| session/project immutable binding 弱 | C1 CLOSE |
| runtime/research 热点单体 | strangler PARTIAL；非 blocker |

### 16.2 Desktop/P1

| Finding | 处置 |
|---|---|
| Binding 先 persist | C1 CLOSE |
| restore error 被吞 | C1 CLOSE |
| lastResearch 污染 | C1 CLOSE |
| listProjects/listTasks/RunSpec continuation 丢失 | C1 CLOSE |
| BindingStore error conflation | C1 CLOSE |
| workspace schema 无 bounds | C1 CLOSE/PARTIAL |
| String coercion 掩盖 drift | touched V1.1 paths C1 CLOSE；全仓清理 DEFER |

### 16.3 Artifact/Task/Result/P1

| Finding | 处置 |
|---|---|
| Export 只写 manifest | C3 CLOSE |
| Stream ticket 无 consume | C3 CLOSE |
| Ticket 无 expiry/one-use bounds | C3 CLOSE |
| Artifact project reachability | C3 CLOSE |
| bytes-first Catalog-later | C3 CLOSE via PublicationIntent |
| compensation 非 durable saga | C3 CLOSE |
| Result/refs/Task 分散终局 | C3 CLOSE |
| provider side effects before Task acceptance | C2 CLOSE |
| Result 无 reconciliation finality | C3 CLOSE |
| role-keyed output overwrite | C3 CLOSE |
| experiment manifest role 错 | touched path C3 CLOSE；experiment execution仍不可用 |
| GC 只有 plan | DEFER；UI 不暴露 execute |

### 16.4 Import/Data/Research/Backtest/P1

| Finding | 处置 |
|---|---|
| manifest 先全量 read | C2 CLOSE |
| symlink/TOCTOU | C2 CLOSE |
| provider PIT/revision/status/corporate-action authority缺失 | 不伪修；PRE_ALPHA/UNKNOWN，STRICT/APPROXIMATE profiles |
| single symbol/top1 退化 | C2/C3 CLOSE |
| observed bar calendar 混淆 | C2 PARTIAL：observed calendar 明标；formal calendar NOT_AVAILABLE |
| no participation/slippage/capacity | C3 CLOSE for research profile |
| future initial holding | C3 CLOSE |
| lot decrement | C3 CLOSE |
| resource admission缺失 | C1–C3 CLOSE |
| rights/fractional/delist不完整 | preflight fail closed；完整支持 DEFER |
| 历史制度矩阵不完整 | coverage gate CLOSE；未覆盖日期保持 NOT_AVAILABLE |
| automatic provider fallback缺失 | 不新增自动 fallback；用户显式换源才是新 request |

### 16.5 Model/Agent/P1

V1.1 核心产品不依赖 Model/Agent：

- Model Lab、Agent Workspace 从一级产品入口撤下。
- L0_READ/L1_DRAFT 权限保持。
- L2/L3 继续 deny。
- run_sync、budget、receipt、sandbox、walk-forward/model registry 等进入 Deferred Gaps。
- 可选 Research Copilot 只有在 L1 draft budget/receipt 闭合时启用。

### 16.6 CI/治理/P1

| Finding | 处置 |
|---|---|
| 普通 CI 仅 Ubuntu | C4 CLOSE |
| 无统一 required product gate | C4 CLOSE；repo setting 若缺则 PENDING_EXTERNAL_REPO_ADMIN |
| code signing/notarization | V1.1 明确 non-goal，NOT_AVAILABLE |
| Actions major tags | C4 CLOSE，pin exact SHA |
| shallow checkout | C4 CLOSE for audit job |
| 静态检查弱 | C4 touched-scope 加强 |
| coverage/property/fault injection缺失 | C1–C4 risk-path CLOSE |
| pip require-hashes/wheelhouse | 有界可做则完成，否则 DEFER，不阻止 V1.1、不宣称 hermetic |
| macOS/Linux package | DEFER |
| 正式 GitHub Release/tag | 本计划不授权；candidate 完成后另行决定 |
| 0 Issue + Deferred Gaps | repo-local Ledger 是本 program truth；外部 issue 需单独授权 |

## 17. V1.1 明确不做

- live trading
- broker/paper broker
- minute/high-frequency data
- fully formal PIT/revision truth
- automatic multi-provider fallback
- provider federation/reconciliation
- complete corporate-action universe
- complete historical rule matrix beyond admitted coverage
- formal BacktestService checkpoint/resume，除非全部契约在同 PR 被真实完成
- experiment DAG/large HPO
- full Model Lab/model registry
- Alpha Mining
- autonomous Agent execution
- L2 EXECUTE / L3 PUBLISH
- production code signing/notarization
- automatic update
- cloud/multi-user
- macOS/Linux release parity
- full portfolio optimizer

这些不是“假装完成”，而是明确 NOT_AVAILABLE 或 DEFERRED。

## 18. Release blockers

V1.1 blocker：

1. Golden Journey A 走不通。
2. Golden Journey B 走不通。
3. enabled action 是假操作。
4. project binding、scope 或 restart persistence 错。
5. data source/unit/result truth 虚假。
6. factor axis、signal timing 或 IC 统计逻辑错误。
7. backtest cash/T+1/slippage/participation/规则 coverage 明显错误。
8. Result 未 VALID 就显示成功。
9. runtime cancel/deadline/exit fencing 不真实。
10. common screen/DPI 不可操作。
11. installer/packaged runtime不能完成 journey。
12. exact candidate required checks 不一致。
13. 缺 independent approval。

不阻止 V1.1、但必须记录：

- 函数仍偏长。
- pagination 超出已声明 bounds 的极端规模。
- full checkpoint/resume。
- advanced AI/Model。
- fully hermetic wheelhouse。
- code signing。
- 更完整 UI polish。
- formal PIT/多源。

## 19. Luna Max 执行算法

对每个 checkpoint 严格重复：

1. 从 Ledger 的 exact_next_action 开始，不能凭聊天摘要重开任务。
2. 读取将修改 owner 的实现和现有测试。
3. 先添加 characterization 或 failing acceptance。
4. 只实现使该 acceptance 通过的最小 owner change。
5. 运行最窄测试。
6. 运行 checkpoint test set。
7. 检查 git diff 和 git status；确认无越界文件。
8. 更新 Ledger：完成项、证据、head、next action、remaining findings。
9. 重算 authority hashes。
10. commit 一次 checkpoint。
11. push 同一 branch。
12. 查询 exact remote head 和 checks。
13. 进入下一 checkpoint。

禁止：

- 因测试难写而删除 contract invariant。
- 因 provider unavailable 注入 fixture。
- 因 UI 需要数据而让 renderer传 canonical numeric truth。
- 因旧代码长而先做全仓重构。
- 因 context 压缩而从 Wave 1 重做。
- 因 CI 绿色而自动升级能力状态。
- 因同一 finding 创建新 branch/PR。

## 20. 自动压缩恢复协议

Ledger 是唯一执行进度真值，聊天不是。

### 20.1 每次更新 Ledger 的时机

- 开始编辑前。
- 每个 acceptance test完成后。
- 每次 commit/push 后。
- 每次 CI 状态变化后。
- 预计即将自动压缩前。
- 任一 STOP/BLOCKED 前。

### 20.2 TASK_PROGRESS 模板

    current_checkpoint: C1 | C2 | C3 | C4
    checkpoint_state: NOT_STARTED | IN_PROGRESS | VALIDATING | COMMITTED | PUSHED | COMPLETE
    last_completed_action: ...
    exact_next_action: ...
    active_acceptance_id: ACC-Cx-yy
    files_currently_modified:
      - ...
    tests:
      last_command: ...
      result: PASS | FAIL | NOT_RUN
      evidence_path: ...
    git:
      admitted_base_sha: ...
      local_head_sha: ...
      remote_head_sha: ...
      tree_sha: ...
      status: CLEAN | DIRTY
    github:
      pr: NOT_CREATED | number
      state: OPEN | CLOSED | MERGED
      checks: PENDING | PASS | FAIL
      independent_review: PENDING | APPROVED
    blockers:
      - ...

exact_next_action 必须是一个可直接执行的动作，例如：

    Add the expired-health regression in tests/ws_e_electron_runtime/supervisor.test.mjs.

不能写：

    Continue Wave 1.

### 20.3 压缩后恢复

1. 重读三份 P0 authority。
2. 重读原始请求、两份附件、本计划。
3. 从 Ledger 顶部重读。
4. 重算 authority hashes。
5. 刷新 Git/GitHub CURRENT。
6. 验证 current worktree、branch、head、dirty status 与 Ledger 一致。
7. 如果不一致，STOP_FOR_REVIEW。
8. 如果一致，只执行 exact_next_action。

不得重复已经在 Ledger 标为 COMPLETE 且有 evidence 的工作。

## 21. PR 创建与关闭协议

四个 checkpoint 都 push 后才创建最终 PR，除非 CI 必须通过 PR event 才能运行；若需早建 PR，也只能建同一个 draft PR。

PR body 必须包含：

- TASK_GOAL
- admitted base SHA/tree
- exact head SHA/tree
- authority version/hashes
- four checkpoint summary
- P0/P1 disposition
- Golden Journey A/B evidence
- truth ceiling
- NOT_AVAILABLE/DEFERRED list
- test/check run URLs
- package/installer/evidence hashes
- clean-machine Job E proof
- provider acceptance truth
- known concerns
- independent review requirement

最终锁头复核：

1. 查询 PR state/base/head。
2. 查询 remote branch head。
3. 查询 exact head checks。
4. 查询 mergeability。
5. 查询 reviews，确认批准者不是作者。
6. 验证 PR head tree 与本地 candidate tree。
7. 重算 authority hashes。
8. git diff admitted-base...head 只含 bounded write set。

输出：

    OPEN
    UNMERGED
    STOP_FOR_INDEPENDENT_REVIEW

无论 checks 多绿都不 merge。普通 merge需要用户之后单独授权和 locked-head proof。

## 22. 最终 evidence index

仓库内 release evidence index 至少链接：

- authority verification
- CURRENT snapshot
- checkpoint commits
- C1 fault matrix
- C2 import/factor/IC goldens
- C3 backtest/publication/result goldens
- C4 UI screen matrix
- Windows integration
- package verification
- clean-machine Job E
- live provider acceptance
- persistence/restart DB probe
- final PR checks/review

每条 evidence 都包含：

- exact SHA
- command/workflow
- timestamp
- environment
- result
- limits
- artifact/log path

没有执行的证据保持 NOT_RUN；外部阻断保持 BLOCKED；等待中的 review/CI 保持 PENDING。

## 23. 计划自身验收与执行交接

### 23.1 计划一致性 gate

只有下列设计条件全部满足，本文状态才可从 PLAN_DRAFT 改为 PLAN_READY：

- P0-01 至 P0-10 各有唯一的 V1.1 处置、checkpoint 和退出条件。
- P1 findings 按 owner 域归组，且每项只能是 CLOSE、DOWNGRADE、PARTIAL 或 DEFER。
- C1 有 8 个、C2 有 10 个、C3 有 13 个、C4 有 11 个命名 acceptance；每个 checkpoint 都有 commit gate。
- Golden Case A 的单标的结果不生成伪 IC；Golden Case B 才拥有横截面统计。
- 2018 至今的可视数据范围与 ExecutionPolicy 实际覆盖的回测范围分离。
- 未兑现的 formal Backtest checkpoint/resume、Artifact GC execute、PIT/revision truth 均未被升级。
- renderer 不拥有 provider 引用、原始字节、canonical numeric truth 或权限升级。
- enabled product actions 都有真实 owner；其余必须 disabled、隐藏或显示明确 reason。
- Product Task success 只能发生在 Result=VALID 且 lineage 可重放之后。
- branch/PR/write set 单一且有界；P0 authority 文件不在写集。
- 自动压缩后可以仅依靠原始请求、本计划和 Ledger 恢复 exact_next_action。
- 最终交付停在 OPEN / UNMERGED / STOP_FOR_INDEPENDENT_REVIEW。

本 gate 只验证计划内部一致性。它不代表任何 V1.1 代码、测试、安装包、clean-machine journey 或 live provider acceptance 已执行；这些状态在实施前全部是 NOT_RUN。

规划期验证结果：PASS。共 10 个唯一 P0 处置、42 个具名 checkpoint acceptance、23 个连续主章节；Golden Case、authority、single-lineage、compaction recovery 和 independent-review 边界均存在。

### 23.2 Luna Max 的第一个 exact_next_action

执行代理收到本文后的第一个动作必须是：

    Re-query GitHub CURRENT, verify authority hashes, admit a clean worktree from fresh origin/main, and create the in-repo V1.1 plan and State Ledger before editing production code.

admission PASS 后，第一项代码工作必须是：

    Add a failing ACC-C1-03 expired-health/late-reply regression to tests/ws_e_electron_runtime/supervisor.test.mjs, record the failing command and output in the Ledger, then implement only the correlated-control owner needed to make that test pass.

如果 admission FAIL，不创建分支、不编辑仓库，Ledger 记录精确失败并 STOP_FOR_REVIEW。
