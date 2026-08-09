# Data Truth / Universe Invariants

## 取舍原则

下列 invariant 只有在官方源码、测试或文档能支持其核心行为时才标为“吸收”。V3 在上游经验之上增加的 publication、hash、admission 约束明确标作 **V3 hardening**，不倒推成上游已有保证。证据编号见 [`SOURCES.md`](./SOURCES.md)。

## I-01 Canonical semantics 不归 provider 所有

**Invariant**：provider adapter 只能把 provider query/result 映射到 V3 canonical meaning，不能定义 canonical identity、calendar、adjustment 或缺失语义。

**Evidence**：OpenBB 将标准 QueryParams/Data 与 fetcher/provider mapping 分开（O1–O5）；vn.py 将 gateway 与标准对象分开（V2–V3）。两者也暴露边界：provider-specific fields、provider ID 和 gateway routing key 仍可能渗入上层（O6、V6）。

**V3 contract consequence**：DataSourceService 接受 connector-version-scoped adapter，Control Catalog 拥有 canonical capability/profile；provider payload 原样保留为 evidence，不能直接成为 Instrument 或 Universe authority。

## I-02 Capability 必须显式、可版本化、可失败

**Invariant**：对每个 connector version 和 canonical operation，系统必须能回答 supported / unavailable / incompatible；不能用空数组、默认 False 或换源表示“成功”。

**Evidence**：OpenBB RegistryMap 与 QueryExecutor 显式枚举能力并对缺 fetcher 报错（O4–O5、O7）。相反，vn.py datafeed 的 warning + empty、database fallback，以及 RQAlpha missing status → False 展示了 silent degradation 的风险（V4、R2）。

**V3 contract consequence**：DataSourceService 只根据已 admission 的 capability 执行；Artifact/Task 记录实际 connector version；formal profile 缺能力返回 typed unavailable。

## I-03 Permanent InstrumentId 不等于任何 provider symbol

**Invariant**：永久 instrument identity 与 `symbol`、`order_book_id`、`vt_symbol`、gateway-local ID 分离；alias 必须按来源和时间解析。

**Evidence**：RQAlpha 明确一个 `order_book_id` 可复用，活跃 instrument 由 id + trading date 唯一确定且歧义失败（R3）；vn.py 的 `vt_symbol` 是 symbol + exchange 的路由键，另带 gateway source（V2、V5–V6）；OpenBB canonical query 仍主要接收 provider-interpreted symbol（O3、O6），不足以成为永久身份。

**V3 contract consequence**：InstrumentService 拥有 `InstrumentId`；alias 至少绑定 connector version、provider code、venue、effective interval、available time、evidence 和 resolution status。

## I-04 Effective time、available time、ingested time 不可混用

**Invariant**：事实适用的市场时间、外界可获得该事实的时间、V3 实际摄取时间是不同轴；PIT 判断以 available time 为上限，不能以 period end 或本地文件修改时间代替。

**Evidence**：Qlib PIT 用发布日期控制修订可见性并由测试锁定（Q4）；RQAlpha instrument/index API 用 trading date/as-of 选择历史状态（R3、R8）。Qlib 仅覆盖部分财务频率，因此“扩展到所有可修订事实”属于 V3 hardening。

**V3 contract consequence**：RawCapture、InstrumentRevision、Universe membership、status、corporate action 均保留三时间；DataSnapshotService admission 验证 `available_time <= knowledge_cutoff`。

## I-05 Revision 必须保留，PIT 查询不可读取“最终最新值”

**Invariant**：同一 effective period 的不同发布版本都可追溯；as-of 查询选择当时已 available 的最近版本，历史重跑不能随着今日修订而变化。

**Evidence**：Qlib PIT 文档直接指出 latest-revision leakage，并在 publication dates 上测试数值切换（Q4）。

**V3 contract consequence**：DataSnapshotService 不覆盖旧 capture/revision；published snapshot 固定所选 revision 集合和 manifest。缺 available-time 证据时 formal snapshot 不得发布。

## I-06 Calendar 是版本化市场事实，不是日期工具函数

**Invariant**：venue/session calendar 必须明确来源、版本、覆盖范围和边界行为；超出覆盖范围应 unavailable，不能回退到“当前 calendar”或钳制到首尾交易日。

**Evidence**：Qlib 将 CalendarProvider 作为一等对象并提供 locate/align（Q1），但 future calendar 缺失会 fallback（Q2）；RQAlpha 区分 calendar type，但 previous/next 越界会端点钳制（R4）。这些反例界定 V3 必须 fail closed 的边界。

**V3 contract consequence**：DataSnapshotService 发布 calendar partition；Task 输入固定 calendar artifact；跨 venue alignment 必须由显式 policy 决定。

## I-07 Universe membership 是时间区间事实

**Invariant**：成员关系至少包含 instrument、effective-from/to、available time、来源证据；查询某日股票池不能用今天的成分列表回填。

**Evidence**：Qlib market 以 symbol + date ranges 表达并可经动态 filter 修改（Q3、Q7）；RQAlpha index components/weights 接受 date 并拒绝未来 date（R8）。两者都未证明 V3 意义上的不可变 published membership，因此 publication 是 V3 hardening。

**V3 contract consequence**：UniverseService resolve 必须绑定 PUBLISHED snapshot、knowledge cutoff 和 membership artifact；unresolved/ambiguous/excluded 均进入 audit artifact。

## I-08 Benchmark 与 Universe 是两个显式输入

**Invariant**：研究样本 Universe、交易可行域和业绩 benchmark 不能因为共享指数名称就隐式相等。

**Evidence**：Qlib workflow 分别配置 market/instruments 与 backtest benchmark（Q6）。

**V3 contract consequence**：UniverseService 输出 membership；Dataset/Task 另行绑定 benchmark reference（如需要），两者 hash 与 evidence 独立。

## I-09 Corporate action、adjustment 与 accounting consequence 分离

**Invariant**：公告/除权/登记/支付/拆分等原始事件，调整因子或调整后价格视图，以及组合现金/数量变化是三类不同事实与计算。

**Evidence**：RQAlpha DataSource 分开 dividends、splits、ex-cum factors，账户模型再按事件日处理头寸（R1–R2、R7）；OpenBB adapter 则展示不同 provider 可能把 actions/adjustment 混入历史行情查询（O6），构成跨源语义风险。

**V3 contract consequence**：DataSnapshotService 分区保存 raw action events 和 factor artifacts；adjusted series 是显式 spec 的 derived artifact；组合后果留给未来执行/回测域。

## I-10 Adjustment 必须声明 basis、anchor、fields，且只应用一次

**Invariant**：任何 adjusted result 都必须能证明输入是否 raw、使用哪个 factor series、前/后复权 anchor、调整哪些 price/volume fields；链路中不得再次调整。

**Evidence**：OpenBB yfinance adapter 和 RQAlpha history bars 都允许 adjustment 改变返回序列（O6、R1–R2），且 provider 默认值不同。RQAlpha synthetic initial factor 还说明缺因子时的便利补值会污染 provenance（R2）。

**V3 contract consequence**：adjustment spec 与 factor artifact 进入 content hash；admission 做 raw/adjusted marker 一致性和 double-application metamorphic test。

## I-11 Suspension、ST、price limits 是相互独立的 temporal facts

**Invariant**：停牌、ST/风险警示和每日涨跌停价不能从成交量、当前名称或固定百分比互相推导；unknown 不能转成 False。

**Evidence**：RQAlpha 为三者提供分开的 DataSource/bar 行为，price-limit 测试覆盖 tick-size 边界（R1–R2、R5）；其 missing status → False 恰好是应拒绝的 failure mode。vn.py DTO 也把 limit fields 作为市场数据字段（V2）。

**V3 contract consequence**：InstrumentService 管身份与修订；DataSnapshotService 保存每个交易日的独立 status/limit facts，附 source capability 和 missingness reason。

## I-12 Published snapshot 与 Universe version 不可变

**Invariant（V3 hardening）**：一旦发布，manifest、bytes、selected revisions、calendar 和 membership artifact 不再原地改变；新数据或修订产生新 version。

**Evidence boundary**：RQAlpha bundle 每日更新（R9）、Qlib 文件/cache 可变（Q1–Q2）、vn.py latest-object cache 会覆盖（V5）。这些成熟系统优化了使用便利，但没有提供 V3 publication guarantee。不可变要求来自现有 V3 Artifact/snapshot contracts（B1–B4），是针对已观察失败面的强化。

**V3 contract consequence**：DataSnapshotService 与 UniverseService 通过 Artifact plane staged → verified → published；Task 只引用 immutable IDs/hashes。

## I-13 Source lineage 是数据本身的一部分

**Invariant**：normalized record 不能丢失 connector/gateway、connector version、provider request、provider revision、capture time 和 raw evidence。字段一致不代表来源可互换。

**Evidence**：vn.py BaseData 保留 `gateway_name`（V2）；OpenBB result metadata/provider 层与 capability map 保留 provider 上下文（O3–O5）。vn.py OMS 仅用 `vt_symbol` 缓存时会覆盖多 gateway 来源（V5），说明 source 必须进入持久身份/分区键。

**V3 contract consequence**：DataSourceService 输出带 lineage 的 capture；DataSnapshotService 不在 provenance 未决时跨源拼接；跨源差异产生 validation finding，不自动择优。

## I-14 无 silent fallback，也无 semantic default

**Invariant**：改变来源、日期范围、calendar、adjustment、missing-status 或 universe membership 的默认行为都必须成为显式、可哈希输入；formal mode 不允许 warning 后继续。

**Evidence**：OpenBB 丢弃 unsupported params、Qlib future-calendar fallback、RQAlpha skip-suspended/pre-adjust 默认、vn.py empty/fallback database 都展示了可复现性和 truth 风险（O6、Q2、R1–R2、V4）。

**V3 contract consequence**：Control Catalog admission 固定 semantic profile；Task canonical input 包含全部 policy；缺失或不兼容返回 typed error。

## I-15 Resolution 必须完整审计，不能静默丢 symbol

**Invariant**：请求集合中的每个输入都要有 resolved / unresolved / ambiguous / excluded + reason；成功结果不能只包含“碰巧能找到”的子集。

**Evidence**：RQAlpha active instrument 对零个或多个匹配显式失败（R3）；OpenBB provider adapter 对 missing symbols 可能只警告（O6），形成需修正的反例。

**V3 contract consequence**：InstrumentService 返回 resolution report；UniverseService publication 需要 total-count reconciliation 和 unresolved audit artifact。

## I-16 Normalization 不等于 truth admission

**Invariant**：把多 provider 数据变成相同 DTO 只证明结构兼容，不证明 calendar、identity、PIT、adjustment、status 或 completeness 一致。

**Evidence**：OpenBB 与 vn.py 都能标准化 provider/gateway 数据（O1–O5、V1–V3），同时仍存在 provider defaults、source ID、empty fallback 和 cache collision 风险（O6、V4–V5）。

**V3 contract consequence**：DataSourceService normalization 后仍进入 DataSnapshotService validation；只有 candidate 通过 capability、identity、calendar、PIT、action、adjustment 和 completeness controls 才能 publish。
