# Data Truth / Universe Failure Modes

## 使用方式

每个 failure mode 都包含触发机制、为什么常规 smoke test 容易漏掉，以及 V3 应由哪个现有平面阻断。证据编号见 [`SOURCES.md`](./SOURCES.md)。这里不把上游缺陷等同于项目整体质量；多数是“便利默认”在 V3 formal truth 场景下不成立。

| ID | Failure mode | 触发与隐蔽性 | V3 detection / containment | Evidence |
|---|---|---|---|---|
| FM-01 | Survivorship bias | 用今日仍上市的 symbol 清单回跑历史；价格看似完整，收益反而“更好” | Universe membership 必须按 effective interval + available time resolve；按 listing/delisting 和 membership 做历史截面 reconciliation | Q1、Q7、R3 |
| FM-02 | Future constituent leakage | 当前或未来发布的指数成分/权重被用于更早日期；仅检查交易日期无法发现“何时知道” | membership 同时验证 effective time 与 available time；knowledge cutoff 后发布的信息不可见；未来 as-of 必须失败 | Q3、R8 |
| FM-03 | Revision leakage | 财报、分类、instrument metadata 或 action 被修订后覆盖旧值，历史重跑读取最终版本 | 保存所有 revisions；同 effective period 在 publication boundary 前后做 golden test；snapshot manifest 固定 revision IDs | Q4、R3 |
| FM-04 | Adjustment double counting | provider 已返回 adjusted bars，V3 又乘 adjustment factor；或 price/volume 使用不一致 factor | raw/adjusted marker、factor lineage、adjustment spec 入 hash；对 `adjust(raw)` 与重复调整做 metamorphic rejection | O6、R1–R2 |
| FM-05 | Provider symbol drift / reuse | provider 改代码、同代码重用、不同 provider 同字符串含义不同 | permanent InstrumentId 与 alias 分离；alias 按 connector version + venue + effective/available interval 解析；歧义 fail closed | R3、V2、V6 |
| FM-06 | Calendar mismatch | A 股节假日、临时休市、不同 venue/session 混用；future calendar 缺失时回退当前版本，或越界钳制端点 | calendar artifact 版本化并声明 coverage；previous/next/align 越界返回 unavailable；跨 venue join 必须指定 policy | Q1–Q2、R4 |
| FM-07 | Suspension unknown → tradable | suspension 数据文件缺失却返回 False；零成交量又被当作停牌或被过滤 | status capability admission；三值/带原因状态；missing partition 阻断 publish；volume 与 suspension 分开测试 | R1–R2 |
| FM-08 | ST history reconstructed from current label | 用今天证券简称推断过去 ST，遗漏摘帽/戴帽时间与信息可得时间 | 独立 ST temporal facts；有效期、available time、evidence；名称 revision 只能作为交叉验证 | R1–R2 |
| FM-09 | Price-limit oversimplification | 固定 10% 规则忽略 ST、板块、制度日期、IPO 日、tick rounding；浮点边界造成一端误判 | 优先保存每日 limit_up/down；规则计算必须 version/venue/profile aware；标量/向量与 tick-edge parity tests | R5、V2 |
| FM-10 | Corporate-action date conflation | announcement、record、ex-date、payable、split 生效日被压成一个日期；同日多事件排序错误 | raw events 保留所有日期与 event IDs；admission 检查因果顺序；同日 split/dividend/reinvestment 与多 payable dates fixture | R1–R2、R7 |
| FM-11 | Inconsistent corporate actions across sources | 一个 provider 给 adjusted bars，另一个给 events/factors；字段名称相同但金额/税/单位不同 | 每源独立 capture；不自动拼接；跨源 reconciliation finding；需要明确 source-of-record policy 才 publish | O6、R1–R2 |
| FM-12 | Silent source fallback | datafeed/database/provider 缺失时改用空实现或 SQLite，任务仍“成功” | connector/version/source ID 是 Run 输入；无 capability 返回 typed unavailable；Artifact lineage 与请求 source 不一致即拒绝 | V4、O4 |
| FM-13 | Unsupported parameter silently dropped | adjustment、actions、interval 等 provider 参数拼错或不支持，只 warning 后使用默认行为 | formal query schema `extra=forbid`；unsupported semantic parameter 为 hard error；记录 normalized request hash | O3、O6 |
| FM-14 | Wall-clock defaults | 未给日期时 adapter 用“今天/若干天前”，同一 Task 输入隔日得到不同数据 | 日期、as-of、knowledge cutoff 必填并进入 canonical input；禁止 adapter 读取 wall clock 决定 formal query | O6 |
| FM-15 | Mutable bundle/source drift | 每日更新 bundle 或本地文件被原地替换；同路径、同配置产生不同回测 | raw bytes content-addressed；snapshot staged/validated/published；Task 只引用 snapshot ID/hash，不引用可变目录 | Q1–Q2、R9、B3–B4 |
| FM-16 | Cache key under-specification | cache 只按 market 或 `vt_symbol`，遗漏 frequency、provider、version、gateway；不同语义结果相互覆盖 | cache key 复用 canonical request hash；source/version/profile/frequency/calendar/snapshot 全部参与；跨 gateway collision test | Q2、V5 |
| FM-17 | Timezone/session erasure | aware timestamp 转数据库本地时间后去掉 tz；夜盘、DST 或跨 venue 记录发生歧义 | 持久化 UTC instant + venue timezone/session date；禁止无 provenance 的 naive datetime；round-trip test | V4 |
| FM-18 | “Skip suspended” changes dataset meaning | history API 默认删除零量/停牌日，使窗口长度、rolling 特征和 Universe 对齐发生变化 | raw series 保留 calendar rows 和显式 missing/status；是否排除由 Dataset spec 决定并入 hash | R1–R2 |
| FM-19 | Dynamic filter future reference | Universe filter/feature 表达式允许负向/未来引用，训练样本在时点 t 看到 t+N | expression/static audit + generated boundary fixtures；materialization 检查每个 dependency 的 available time | Q3 |
| FM-20 | Benchmark / Universe accidental coupling | 用 benchmark constituents 当研究 Universe，或换 benchmark 时样本集合暗变 | 两个输入独立 ID/hash；Task manifest 同时记录；改变任一项产生新 Run | Q6 |
| FM-21 | Partial resolution hidden as success | provider 返回部分 symbols 并仅 warning；下游把缩小后的截面当完整 Universe | requested/resolved/unresolved/ambiguous counts 必须守恒；publication 需要 resolution audit artifact | O6、R3 |
| FM-22 | Permissive extra fields become shadow contract | provider extra fields被下游长期依赖，绕过 canonical versioning；provider 更新后静默改变 | provider namespace 隔离；只有 admission 后的 canonical fields 可进入 formal dataset；extra payload 仅作 evidence | O3、O5 |
| FM-23 | Synthetic factor hides missing history | 为便于计算，在缺失 corporate-action factor 时补 1，结果数值合理但 provenance 不完整 | 区分 provider-observed、derived、synthetic；formal adjustment 禁止无 evidence 补值；gap 进入 validation finding | R2 |
| FM-24 | Loose health thresholds promoted to truth proof | 为兼容不同 provider 放宽股票数/收益范围，smoke test 通过但局部 PIT/identity 已错 | smoke checks 只作 telemetry；admission 使用精确结构/时序/invariant tests 和可审计 exceptions | Q7 |
| FM-25 | Event object mutation after publication | callback 后缓存同一可变对象，后续修改改变历史观察；“请勿修改”只是约定 | 跨边界复制/冻结；published artifact bytes rehash；读取对象不可原地更新 | V3、B4 |
| FM-26 | Order/fill semantics consume wrong truth | matcher 对 suspension、limits、liquidity、lot size 的假设与数据 profile 不一致，产生虚假成交 | WS-F 先保证 status/limit/lot/calendar facts 可用；执行与 matcher 行为留到 future contract，不在 Data Truth 层实现 | R5–R6 |

## 高风险组合

单个 failure mode 往往不会立刻显现，组合才最危险：

1. **FM-01 + FM-02 + FM-03**：今日成分 + 最终修订值构成“完美历史”，是典型 research leakage。
2. **FM-04 + FM-10 + FM-23**：调整行情、事件和补齐因子混用，净值可能连续但经济含义错误。
3. **FM-06 + FM-07 + FM-18**：错误 calendar、missing-as-not-suspended 和删除零量日共同改变窗口长度。
4. **FM-05 + FM-12 + FM-16**：symbol 重用、换源 fallback 和欠规格 cache 使错误记录以正确 key 命中。
5. **FM-13 + FM-14 + FM-15**：参数被丢、日期取当前、bundle 原地更新，使同一用户请求无法复现。

V3 的 containment 应集中在已有的 connector admission、Instrument resolution、snapshot validation/publication、Universe resolution、Artifact hash 和 Task canonical input 上，而不是新增一套平行 truth engine。
